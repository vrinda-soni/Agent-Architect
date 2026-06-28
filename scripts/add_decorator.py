import re

with open("frontend/chainlit_app.py", "r") as f:
    content = f.read()

decorator_code = """
from functools import wraps

def prevent_concurrent(func):
    @wraps(func)
    async def wrapper(action: cl.Action, *args, **kwargs):
        # Also quickly remove the button visually
        try:
            await action.remove()
        except Exception:
            pass
            
        if cl.user_session.get("is_processing"):
            await cl.Message(content="⏳ Please wait! A task is currently running.").send()
            return
        cl.user_session.set("is_processing", True)
        try:
            return await func(action, *args, **kwargs)
        finally:
            cl.user_session.set("is_processing", False)
    return wrapper

"""

# Insert decorator before the first action callback
insert_pos = content.find("@cl.action_callback")
if "def prevent_concurrent" not in content:
    content = content[:insert_pos] + decorator_code + content[insert_pos:]

# Add @prevent_concurrent to specific heavy callbacks
targets = [
    "run_task_agent",
    "hitl1_approve",
    "hitl1_regen",
    "hitl2_approve",
    "hitl2_regen_plan",
    "hitl2_rerun_feas",
    "run_estimation",
    "hitl3_approve",
    "hitl3_regen",
    "generate_report",
]

for t in targets:
    pattern = f'@cl.action_callback("{t}")\nasync def'
    replacement = f'@cl.action_callback("{t}")\n@prevent_concurrent\nasync def'
    content = content.replace(pattern, replacement)

with open("frontend/chainlit_app.py", "w") as f:
    f.write(content)
print("Updated chainlit_app.py with prevent_concurrent decorator!")
