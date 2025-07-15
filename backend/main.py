import os
import httpx
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlencode
from dotenv import load_dotenv
from github import Github

load_dotenv()

GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"]
GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"]
OAUTH_CALLBACK_URL = os.environ["OAUTH_CALLBACK_URL"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama3-70b-8192")

app = FastAPI()
user_tokens = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def require_user_token(state: str):
    token = user_tokens.get(state)
    if not token:
        raise HTTPException(401, detail="User not logged in or token expired")
    return token

@app.get("/login/github")
async def login_github():
    state = str(uuid.uuid4())
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": OAUTH_CALLBACK_URL,
        "scope": "repo",
        "state": state
    }
    github_auth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return {"auth_url": github_auth_url, "state": state}

@app.get("/auth/github/callback")
async def github_callback(code: str, state: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": OAUTH_CALLBACK_URL,
                "state": state
            },
            headers={"Accept": "application/json"}
        )
        token_json = response.json()
        access_token = token_json.get("access_token")
        if not access_token:
            raise HTTPException(401, detail="GitHub OAuth failed")
        user_tokens[state] = access_token
    return RedirectResponse(f"http://localhost:8501/?state={state}")

@app.get("/api/list-prs")
async def list_prs(repo_url: str, state: str):
    token = require_user_token(state)
    owner_repo = repo_url.rstrip("/").replace("https://github.com/", "")
    gh = Github(token)
    repo = gh.get_repo(owner_repo)
    prs = repo.get_pulls(state="open")
    result = []
    for pr in prs:
        result.append({
            "number": pr.number,
            "title": pr.title,
            "author": pr.user.login,
            "body": pr.body,
            "url": pr.html_url,
            "commit_count": pr.commits
        })
    return {"prs": result}

@app.get("/api/pr-commits-with-diffs")
async def pr_commits_with_diffs(repo_url: str, pr_number: int, state: str):
    try:
        token = require_user_token(state)
        owner_repo = repo_url.rstrip("/").replace("https://github.com/", "")
        gh = Github(token)
        repo = gh.get_repo(owner_repo)
        pr = repo.get_pull(pr_number)
        commits = pr.get_commits()
        out = []
        for c in commits:
            commit_obj = repo.get_commit(c.sha)
            files = []
            for f in commit_obj.files:
                files.append({
                    "filename": f.filename,
                    "patch": getattr(f, "patch", "(No patch available)")
                })
            out.append({
                "sha": c.sha,
                "message": c.commit.message,
                "author": c.author.login if c.author else "",
                "date": c.commit.author.date.isoformat(),
                "files": files
            })
        return {"commits": out}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/pr-status")
async def pr_status(repo_url: str, pr_number: int, state: str):
    try:
        token = require_user_token(state)
        owner_repo = repo_url.rstrip("/").replace("https://github.com/", "")
        gh = Github(token)
        repo = gh.get_repo(owner_repo)
        pr = repo.get_pull(pr_number)
        commit = repo.get_commit(pr.head.sha)
        combined_status = commit.get_combined_status()
        checks = []
        for status in combined_status.statuses:
            checks.append({
                "context": status.context,
                "state": status.state,
                "description": status.description,
                "target_url": status.target_url,
                "created_at": status.created_at.isoformat(),
            })
        return {
            "state": combined_status.state,
            "checks": checks,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/pr-check-summaries")
async def pr_check_summaries(repo_url: str, pr_number: int, state: str):
    """
    Returns all GitHub Action check runs summaries (e.g. linter/test output) for the PR's latest commit,
    including inline annotations for each run (if present).
    """
    try:
        token = require_user_token(state)
        owner_repo = repo_url.rstrip("/").replace("https://github.com/", "")
        gh = Github(token)
        repo = gh.get_repo(owner_repo)
        pr = repo.get_pull(pr_number)
        head_sha = pr.head.sha

        # Fetch check runs from GitHub v3 API
        import requests as pyrequests
        url = f"https://api.github.com/repos/{owner_repo}/commits/{head_sha}/check-runs"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
        resp = pyrequests.get(url, headers=headers)
        result = []
        if resp.ok:
            data = resp.json()
            for run in data.get("check_runs", []):
                summary = run.get("output", {}).get("summary") or ""
                title = run.get("name")
                status = run.get("conclusion") or run.get("status")
                details_url = run.get("details_url")
                # Inline annotations:
                annotations = []
                output = run.get("output", {})
                # Sometimes, the output can have up to 50 annotations. If there are more, use pagination.
                anns = output.get("annotations", [])
                if anns:
                    annotations = anns
                result.append({
                    "title": title,
                    "status": status,
                    "summary": summary,
                    "annotations": annotations,
                    "details_url": details_url,
                })
        return {"checks": result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/review-pr")
async def review_pr(repo_url: str, pr_number: int, state: str):
    try:
        token = require_user_token(state)
        owner_repo = repo_url.rstrip("/").replace("https://github.com/", "")
        gh = Github(token)
        repo = gh.get_repo(owner_repo)
        pr = repo.get_pull(pr_number)
        review_text = ""
        for file in pr.get_files():
            if not file.patch:
                continue
            review_text += f"\n# File: {file.filename}\n{file.patch}\n"
        prompt = f"""You are a senior software engineer. Review the following GitHub pull request diff for code quality, bugs, and improvement suggestions. Reply in concise bullet points.
{review_text}
"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 512
                },
                timeout=120
            )
            resp.raise_for_status()
            output = resp.json()["choices"][0]["message"]["content"]
        return {"review": output.strip()}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/approve-pr")
async def approve_pr(repo_url: str, pr_number: int, state: str):
    try:
        token = require_user_token(state)
        owner_repo = repo_url.rstrip("/").replace("https://github.com/", "")
        gh = Github(token)
        repo = gh.get_repo(owner_repo)
        pr = repo.get_pull(pr_number)
        pr.create_review(event="APPROVE", body="Approved by AI Review Agent and user.")
        return {"status": "approved"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/github-user")
async def github_user(state: str):
    try:
        token = require_user_token(state)
        gh = Github(token)
        user = gh.get_user()
        return {"login": user.login, "name": user.name, "avatar_url": user.avatar_url}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)
