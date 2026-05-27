#!/usr/bin/env bash

set -euo pipefail

ACTION="${1:-help}"
PROJECT_DIR="${2:-$(pwd)}"

DEFAULT_BRANCH="main"
REMOTE_NAME="origin"

cd "$PROJECT_DIR" || {
  echo "[ERROR] 프로젝트 경로로 이동할 수 없습니다: $PROJECT_DIR"
  exit 1
}

DEVICE="$(hostname)"
USER_NAME="$(whoami)"
NOW="$(date "+%Y-%m-%d %H:%M:%S %Z")"

print_header() {
  echo "============================================================"
  echo " Git Sync Helper"
  echo " Project : $(pwd)"
  echo " Device  : $DEVICE"
  echo " User    : $USER_NAME"
  echo " Time    : $NOW"
  echo "============================================================"
}

is_git_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1
}

has_remote() {
  git remote get-url "$REMOTE_NAME" >/dev/null 2>&1
}

current_branch() {
  local branch
  branch="$(git branch --show-current 2>/dev/null || true)"

  if [ -z "$branch" ]; then
    branch="$DEFAULT_BRANCH"
  fi

  echo "$branch"
}

ensure_gitignore() {
  if [ -f ".gitignore" ]; then
    return 0
  fi

  echo "[INFO] .gitignore 파일이 없어 기본 .gitignore를 생성합니다."

  cat > .gitignore <<'EOF'
# Python
__pycache__/
*.py[cod]
*.pyo
.venv/
venv/
env/
.env
.env.*

# Jupyter
.ipynb_checkpoints/

# Logs
*.log
logs/
data/logs/
storage/logs/

# Runtime data
data/stream/
data/cache/
data/packages/
data/queue/
data/sent/
data/failed/
storage/events/
storage/uploads/
storage/tmp/
storage/cache/

# DB / local state
*.db
*.sqlite
*.sqlite3

# Model weights / heavy artifacts
*.pt
*.pth
*.onnx
*.engine
*.bin
*.safetensors

# Archives
*.zip
*.tar
*.tar.gz
*.7z

# OS / IDE
.DS_Store
.idea/
.vscode/
EOF
}

init_git_repo() {
  if is_git_repo; then
    echo "[OK] 이미 Git 저장소입니다."
    return 0
  fi

  echo "[WARN] 현재 디렉터리는 Git 저장소가 아닙니다."
  read -r -p "이 디렉터리를 Git 저장소로 초기화할까요? [y/N]: " answer

  case "$answer" in
    y|Y|yes|YES)
      echo "[INFO] git init 실행..."
      git init
      git branch -M "$DEFAULT_BRANCH"
      ensure_gitignore
      ;;
    *)
      echo "[CANCEL] Git 저장소 초기화를 취소했습니다."
      exit 1
      ;;
  esac
}

configure_remote_manual() {
  local remote_url

  if has_remote; then
    echo "[OK] 이미 remote가 설정되어 있습니다."
    git remote -v
    return 0
  fi

  echo
  echo "[INFO] GitHub에서 repository를 먼저 만들었다면 URL을 입력하세요."
  echo "예시:"
  echo "  https://github.com/USERNAME/REPOSITORY.git"
  echo "  git@github.com:USERNAME/REPOSITORY.git"
  echo
  read -r -p "GitHub remote URL 입력: " remote_url

  if [ -z "$remote_url" ]; then
    echo "[ERROR] remote URL이 비어 있습니다."
    exit 1
  fi

  git remote add "$REMOTE_NAME" "$remote_url"
  echo "[OK] remote 추가 완료:"
  git remote -v
}

configure_remote_with_gh() {
  if has_remote; then
    echo "[OK] 이미 remote가 설정되어 있습니다."
    git remote -v
    return 0
  fi

  if ! command -v gh >/dev/null 2>&1; then
    echo "[WARN] GitHub CLI(gh)가 설치되어 있지 않습니다."
    echo "[INFO] 수동 remote URL 입력 방식으로 진행합니다."
    configure_remote_manual
    return 0
  fi

  echo
  echo "[INFO] GitHub CLI를 사용해서 GitHub repository를 만들 수 있습니다."
  echo "단, gh auth login이 되어 있어야 합니다."
  echo
  read -r -p "GitHub에 새 repository를 자동 생성할까요? [y/N]: " use_gh

  case "$use_gh" in
    y|Y|yes|YES)
      local repo_name visibility
      read -r -p "Repository 이름 입력 예: edge-to-server-grad: " repo_name

      if [ -z "$repo_name" ]; then
        echo "[ERROR] repository 이름이 비어 있습니다."
        exit 1
      fi

      echo "공개 범위를 선택하세요."
      echo "  1) private"
      echo "  2) public"
      read -r -p "선택 [1/2, 기본 1]: " visibility_choice

      case "${visibility_choice:-1}" in
        2)
          visibility="--public"
          ;;
        *)
          visibility="--private"
          ;;
      esac

      echo "[INFO] gh repo create 실행..."
      gh repo create "$repo_name" "$visibility" --source=. --remote="$REMOTE_NAME"

      echo "[OK] GitHub repository 생성 및 remote 연결 완료:"
      git remote -v
      ;;
    *)
      configure_remote_manual
      ;;
  esac
}

ensure_remote() {
  if has_remote; then
    echo "[OK] remote 확인:"
    git remote -v
  else
    configure_remote_with_gh
  fi
}

ensure_first_commit_if_needed() {
  local commit_count

  commit_count="$(git rev-list --count HEAD 2>/dev/null || echo 0)"

  if [ "$commit_count" = "0" ]; then
    echo "[INFO] 아직 commit이 없습니다. initial commit을 생성합니다."

    ensure_gitignore

    git add .

    if [ -z "$(git status --porcelain)" ]; then
      echo "[WARN] commit할 파일이 없습니다."
      return 0
    fi

    git commit -m "init: initial project commit"
  fi
}

cmd_setup() {
  print_header
  init_git_repo
  ensure_gitignore
  ensure_remote
  ensure_first_commit_if_needed

  local branch
  branch="$(current_branch)"

  echo "[INFO] 첫 push를 수행합니다."
  git push -u "$REMOTE_NAME" "$branch"

  echo "[DONE] setup 완료"
}

cmd_status() {
  print_header
  init_git_repo

  echo
  echo "[Git status]"
  git status

  echo
  echo "[Remote]"
  if has_remote; then
    git remote -v
  else
    echo "remote가 아직 없습니다."
  fi

  echo
  echo "[Branch]"
  git branch -vv || true
}

cmd_pull() {
  print_header
  init_git_repo
  ensure_remote

  local branch
  branch="$(current_branch)"

  echo "[INFO] Pull from GitHub..."
  echo "Branch: $branch"

  git pull "$REMOTE_NAME" "$branch" --no-rebase
}

cmd_push() {
  print_header
  init_git_repo
  ensure_gitignore
  ensure_remote
  ensure_first_commit_if_needed

  local branch
  branch="$(current_branch)"

  echo "[INFO] Push to GitHub..."
  echo "Branch: $branch"

  git status

  if [ -z "$(git status --porcelain)" ]; then
    echo "[OK] 변경사항이 없습니다."

    # upstream이 없는 초기 상태일 수 있으므로 push 연결은 한 번 시도
    git push -u "$REMOTE_NAME" "$branch" || true
    exit 0
  fi

  git add .

  local commit_msg
  commit_msg="sync: $NOW from $DEVICE by $USER_NAME"

  git commit -m "$commit_msg"

  git push -u "$REMOTE_NAME" "$branch"

  echo "[DONE] push 완료"
}

cmd_force_pull() {
  print_header
  init_git_repo
  ensure_remote

  local branch
  branch="$(current_branch)"

  echo "[DANGER] 이 명령은 로컬 변경사항을 버리고 원격 상태로 맞춥니다."
  read -r -p "정말 진행할까요? [y/N]: " answer

  case "$answer" in
    y|Y|yes|YES)
      git fetch "$REMOTE_NAME"
      git reset --hard "$REMOTE_NAME/$branch"
      git clean -fd
      echo "[DONE] force-pull 완료"
      ;;
    *)
      echo "[CANCEL] 취소했습니다."
      ;;
  esac
}

print_help() {
  cat <<EOF
사용법:
  ./sync.sh setup [프로젝트_경로]
  ./sync.sh status [프로젝트_경로]
  ./sync.sh pull [프로젝트_경로]
  ./sync.sh push [프로젝트_경로]
  ./sync.sh force-pull [프로젝트_경로]

설명:
  setup      Git 저장소가 아니면 git init 수행, remote 설정, initial commit, 첫 push까지 진행
  status     현재 Git 상태, remote, branch 확인
  pull       GitHub에서 현재 branch pull
  push       변경사항 commit 후 GitHub push
  force-pull 로컬 변경사항을 버리고 원격 branch 상태로 강제 동기화

예시:
  ./sync.sh setup
  ./sync.sh push
  ./sync.sh pull
  ./sync.sh status /home/jihoney/workdir/backup_dir/backup/donga_univ/GRAD

주의:
  - GitHub repository 자동 생성을 원하면 gh CLI가 필요합니다.
  - gh가 없으면 GitHub에서 repository를 직접 만든 뒤 remote URL을 입력하면 됩니다.
EOF
}

case "$ACTION" in
  setup)
    cmd_setup
    ;;
  status)
    cmd_status
    ;;
  pull)
    cmd_pull
    ;;
  push)
    cmd_push
    ;;
  force-pull)
    cmd_force_pull
    ;;
  help|-h|--help)
    print_help
    ;;
  *)
    echo "[ERROR] 알 수 없는 ACTION: $ACTION"
    echo
    print_help
    exit 1
    ;;
esac