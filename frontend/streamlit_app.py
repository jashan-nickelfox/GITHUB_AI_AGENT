import streamlit as st
import requests

BACKEND = "http://localhost:8000"

st.set_page_config(page_title="AI PR Review Agent", page_icon="🤖", layout="centered")
st.title("🤖 AI PR Review Agent (GitHub)")

if "oauth_state" not in st.session_state:
    st.session_state.oauth_state = ""
if "is_logged_in" not in st.session_state:
    st.session_state.is_logged_in = False
if "prs" not in st.session_state:
    st.session_state.prs = []
if "review" not in st.session_state:
    st.session_state.review = ""
if "repo_url" not in st.session_state:
    st.session_state.repo_url = ""
if "user_info" not in st.session_state:
    st.session_state.user_info = {}

query_params = st.query_params
if "state" in query_params:
    st.session_state.oauth_state = query_params["state"]
    st.session_state.is_logged_in = True

def get_github_user(state):
    try:
        resp = requests.get(f"{BACKEND}/api/github-user", params={"state": state}, timeout=20)
        if resp.ok:
            return resp.json()
    except Exception as e:
        print("Error fetching user info:", e)
    return {}

def get_pr_status(repo_url, pr_number, state):
    try:
        resp = requests.get(
            f"{BACKEND}/api/pr-status",
            params={"repo_url": repo_url, "pr_number": pr_number, "state": state},
            timeout=20
        )
        if resp.ok:
            return resp.json()
    except Exception as e:
        print("Error fetching PR status:", e)
    return {"state": "unknown", "checks": []}

def get_pr_check_summaries(repo_url, pr_number, state):
    try:
        resp = requests.get(
            f"{BACKEND}/api/pr-check-summaries",
            params={"repo_url": repo_url, "pr_number": pr_number, "state": state},
            timeout=30
        )
        if resp.ok:
            return resp.json().get("checks", [])
    except Exception as e:
        print("Error fetching check summaries:", e)
    return []

def get_pr_commits_with_diffs(repo_url, pr_number, state):
    try:
        resp = requests.get(
            f"{BACKEND}/api/pr-commits-with-diffs",
            params={"repo_url": repo_url, "pr_number": pr_number, "state": state},
            timeout=40
        )
        if resp.ok:
            return resp.json().get("commits", [])
    except Exception as e:
        print("Error fetching commits with diffs:", e)
    return []

# Show login or user info
if not st.session_state.is_logged_in or not st.session_state.oauth_state:
    st.write("Please log in with GitHub to continue.")
    if st.button("Login with GitHub"):
        resp = requests.get(f"{BACKEND}/login/github")
        if resp.ok:
            login_data = resp.json()
            auth_url = login_data["auth_url"]
            st.markdown(f'<a href="{auth_url}" target="_blank">Click here to login via GitHub</a>', unsafe_allow_html=True)
    st.stop()

if st.session_state.oauth_state and not st.session_state.user_info:
    st.session_state.user_info = get_github_user(st.session_state.oauth_state)

userinfo = st.session_state.user_info
if userinfo and userinfo.get("login"):
    col1, col2 = st.columns([1, 10])
    with col1:
        st.image(userinfo.get("avatar_url"), width=40)
    with col2:
        st.markdown(f"Logged in as **{userinfo.get('name') or userinfo.get('login')}**")

st.session_state.repo_url = st.text_input(
    "Paste your GitHub repository URL",
    value=st.session_state.repo_url or "",
    placeholder="https://github.com/owner/repo"
)

if st.session_state.repo_url and st.button("List PRs"):
    try:
        resp = requests.get(
            f"{BACKEND}/api/list-prs",
            params={"repo_url": st.session_state.repo_url, "state": st.session_state.oauth_state},
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        st.session_state.prs = data.get("prs", [])
        st.session_state.review = ""
    except Exception as e:
        st.error(f"Error fetching PRs: {e}")
        st.session_state.prs = []
        st.session_state.review = ""

if st.session_state.prs:
    st.subheader("Open Pull Requests")
    for pr in st.session_state.prs:
        with st.expander(f"#{pr['number']}: {pr['title']} (by {pr['author']})"):
            st.markdown(f"[View on GitHub]({pr['url']})")
            st.markdown(f"**Commits in this PR:** `{pr.get('commit_count', '?')}`")

            # Show latest CI status
            pr_status = get_pr_status(st.session_state.repo_url, pr['number'], st.session_state.oauth_state)
            state_icon = {
                "success": "✅",
                "failure": "❌",
                "pending": "⏳",
                "unknown": "❔"
            }
            st.markdown(
                f"**Latest CI Status:** {state_icon.get(pr_status['state'], '❔')} `{pr_status['state']}`"
            )
            if pr_status.get("checks"):
                st.markdown("**Status Checks:**")
                for check in pr_status["checks"]:
                    st.markdown(
                        f"- **{check['context']}**: {state_icon.get(check['state'], '❔')} "
                        f"`{check['state']}` — {check['description'] or ''} "
                        f"[Details]({check['target_url']})"
                    )

            # Show inline linter/test summaries and annotations
            check_summaries = get_pr_check_summaries(st.session_state.repo_url, pr['number'], st.session_state.oauth_state)
            if check_summaries:
                st.markdown("**Inline Lint/Test Results:**")
                for run in check_summaries:
                    status_icon2 = {
                        "success": "✅",
                        "failure": "❌",
                        "neutral": "🟡",
                        "cancelled": "🚫",
                        "timed_out": "⏱️",
                        "action_required": "⚠️"
                    }
                    icon = status_icon2.get((run["status"] or "").lower(), "❔")
                    st.markdown(f"- **{run['title']}**: {icon} `{run['status']}`")
                    if run["summary"]:
                        st.code(run["summary"], language="markdown")
                    # Display each annotation inline:
                    if run.get("annotations"):
                        for anno in run["annotations"]:
                            st.markdown(
                                f"`{anno.get('path', 'file')}` "
                                f"**L{anno.get('start_line', '?')}** "
                                f"`{anno.get('annotation_level', '').upper()}` - "
                                f"{anno.get('message', '')}"
                            )
                    if run.get("details_url"):
                        st.markdown(f"[Full Details]({run['details_url']})")

            # Show all commits with code/diffs
            if st.button(f"Show All Commits & Diffs for PR #{pr['number']}", key=f"commits_{pr['number']}"):
                commits = get_pr_commits_with_diffs(st.session_state.repo_url, pr['number'], st.session_state.oauth_state)
                if commits:
                    for c in commits:
                        st.markdown(
                            f"**Commit `{c['sha'][:7]}` by `{c['author']}` on `{c['date'][:10]}`**<br/>"
                            f"<span style='color:#888'>{c['message']}</span>",
                            unsafe_allow_html=True
                        )
                        for f in c['files']:
                            st.markdown(
                                f"<details><summary>{f['filename']}</summary>\n\n"
                                f"```diff\n{f['patch']}\n```\n</details>",
                                unsafe_allow_html=True
                            )
                else:
                    st.info("No commits found or unable to load.")

            # Review/Approve buttons
            if st.button(f"Review PR #{pr['number']}", key=f"review_{pr['number']}"):
                st.session_state.review = "Reviewing... (may take up to 1 min)"
                try:
                    r = requests.get(
                        f"{BACKEND}/api/review-pr",
                        params={
                            "repo_url": st.session_state.repo_url,
                            "pr_number": pr['number'],
                            "state": st.session_state.oauth_state
                        },
                        timeout=120
                    )
                    if r.headers.get('Content-Type', '').startswith('application/json'):
                        review_data = r.json()
                        if "review" in review_data:
                            st.session_state.review = review_data["review"]
                        elif "error" in review_data:
                            st.session_state.review = f"Error: {review_data['error']}"
                        else:
                            st.session_state.review = "No review returned."
                    else:
                        st.session_state.review = f"Error: {r.text}"
                except Exception as e:
                    st.session_state.review = f"Error fetching review: {e}"
            if st.session_state.review and st.session_state.review != "Reviewing... (may take up to 1 min)":
                if st.session_state.review.startswith("Error"):
                    st.error(st.session_state.review)
                else:
                    st.info(st.session_state.review)
            if st.button(f"Approve PR #{pr['number']}", key=f"approve_{pr['number']}"):
                try:
                    r = requests.post(
                        f"{BACKEND}/api/approve-pr",
                        params={
                            "repo_url": st.session_state.repo_url,
                            "pr_number": pr['number'],
                            "state": st.session_state.oauth_state
                        },
                        timeout=20
                    )
                    if r.ok:
                        st.success("PR Approved!")
                    else:
                        st.error(f"Failed to approve PR: {r.text}")
                except Exception as e:
                    st.error(f"Failed to approve PR: {e}")

if st.session_state.is_logged_in and st.session_state.oauth_state:
    if st.button("Logout"):
        st.session_state.oauth_state = ""
        st.session_state.is_logged_in = False
        st.session_state.prs = []
        st.session_state.review = ""
        st.session_state.repo_url = ""
        st.session_state.user_info = {}
        st.query_params.clear()
        st.experimental_rerun()
