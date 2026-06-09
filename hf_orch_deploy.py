# deploy.py — upload the clip-server folder to its Hugging Face Space
import sys
from huggingface_hub import HfApi

REPO_ID = "junaidOrchestra/Orchestrator"   # your Space 
FOLDER  = "orchestrator"          # local folder whose contents become the Space root

def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else "Deploy clip-server"
    info = HfApi().upload_folder(
        folder_path=FOLDER,
        repo_id=REPO_ID,
        repo_type="space",
        commit_message=msg,
        ignore_patterns=[".env", "*.env", "**/__pycache__/**", "*.pyc",
                         ".venv/**", ".git/**"],
    )
    print(f"Deployed -> {info}")

if __name__ == "__main__":
    main()