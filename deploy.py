#!/usr/bin/env python3
"""
🚀 daizhigev20 一键部署脚本

使用方法：
    python3 deploy.py
    python3 deploy.py --port 9000
    python3 deploy.py --dir /opt/daizhigev20 --skip-docker
"""

import os
import sys
import subprocess
import time
import argparse
import json
from pathlib import Path
from typing import Optional, Tuple


# ============================================================================
# 颜色输出
# ============================================================================

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_step(msg: str):
    print(f"{Colors.BLUE}▶ {msg}{Colors.ENDC}")


def print_success(msg: str):
    print(f"{Colors.GREEN}✅ {msg}{Colors.ENDC}")


def print_error(msg: str):
    print(f"{Colors.RED}❌ {msg}{Colors.ENDC}")


def print_warning(msg: str):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.ENDC}")


def print_header(msg: str):
    width = 70
    print(f"\n{Colors.BOLD}{'╔' + '═' * (width - 2) + '╗'}{Colors.ENDC}")
    print(f"{Colors.BOLD}║  {msg:<{width - 5}}║{Colors.ENDC}")
    print(f"{Colors.BOLD}{'╚' + '═' * (width - 2) + '╝'}{Colors.ENDC}\n")


# ============================================================================
# 工具函数
# ============================================================================

def run_command(cmd: str, check: bool = True, capture: bool = False) -> Tuple[int, str]:
    """执行命令"""
    try:
        if capture:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, check=False
            )
            return result.returncode, result.stdout.strip()
        else:
            result = subprocess.run(cmd, shell=True, check=check)
            return result.returncode, ""
    except Exception as e:
        if check:
            print_error(f"命令执行失败: {e}")
            sys.exit(1)
        return 1, ""


def command_exists(cmd: str) -> bool:
    """检查命令是否存在"""
    code, _ = run_command(f"command -v {cmd}", check=False, capture=True)
    return code == 0


def check_port_available(port: int) -> bool:
    """检查端口是否可用"""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        return result != 0
    except:
        return True


# ============================================================================
# 部署类
# ============================================================================

class Deployer:
    def __init__(
        self,
        repo_url: str = "https://github.com/leanderyu321-cyber/daizhigev20.git",
        project_dir: Optional[str] = None,
        api_port: int = 8000,
        skip_docker: bool = False,
    ):
        self.repo_url = repo_url
        self.project_dir = Path(project_dir) if project_dir else Path.home() / "daizhigev20"
        self.api_port = api_port
        self.skip_docker = skip_docker
        self.es_port = 9200
        self.api_host = "0.0.0.0"
        self.venv_dir = self.project_dir / ".venv"
        self.python_exe = self.venv_dir / "bin" / "python"

    def pre_check(self) -> bool:
        """前置检查"""
        print_header("📋 环境检查")

        # 检查必要命令
        required = ["git", "python3"]
        if not self.skip_docker:
            required.extend(["docker", "docker-compose"])

        for cmd in required:
            if command_exists(cmd):
                print_success(f"{cmd} 已安装")
            else:
                print_error(f"{cmd} 未安装")
                return False

        # 检查 Python 版本
        code, output = run_command("python3 --version", capture=True)
        print_success(f"Python 版本: {output}")

        # 检查端口
        if not check_port_available(self.api_port):
            print_warning(f"端口 {self.api_port} 已被占用，请使用其他端口")
            return False

        return True

    def setup_project(self) -> bool:
        """设置项目"""
        print_header("📥 项目设置")

        if (self.project_dir / ".git").exists():
            print_step("更新现有项目...")
            run_command(f"cd {self.project_dir} && git pull", check=False)
            print_success("项目已更新")
        else:
            print_step("克隆项目...")
            self.project_dir.parent.mkdir(parents=True, exist_ok=True)
            run_command(f"git clone {self.repo_url} {self.project_dir}")
            print_success("项目已克隆")

        return True

    def setup_python_env(self) -> bool:
        """设置 Python 环境"""
        print_header("🐍 Python 环境配置")

        # 创建虚拟环境
        if not self.venv_dir.exists():
            print_step("创建虚拟环境...")
            run_command(f"python3 -m venv {self.venv_dir}")
            print_success("虚拟环境已创建")

        # 升级 pip
        print_step("升级 pip...")
        run_command(f"{self.python_exe} -m pip install --upgrade pip setuptools wheel")
        print_success("pip 已升级")

        # 安装依赖
        requirements = self.project_dir / "requirements.txt"
        if requirements.exists():
            print_step("安装依赖包（可能需要几分钟）...")
            run_command(f"{self.python_exe} -m pip install -r {requirements}")
            print_success("依赖包已安装")
        else:
            print_error("requirements.txt 不存在")
            return False

        return True

    def start_docker(self) -> bool:
        """启动 Docker 服务"""
        if self.skip_docker:
            print_header("⏭️  跳过 Docker 启动")
            print_warning("确保 Elasticsearch 已在 localhost:9200 运行")
            return True

        print_header("🐳 Docker 服务启动")

        docker_compose = self.project_dir / "docker-compose.yml"
        if not docker_compose.exists():
            print_error("docker-compose.yml 不存在")
            return False

        print_step("启动 Docker Compose 服务...")
        run_command(f"cd {self.project_dir} && docker-compose up -d")
        print_success("Docker 服务已启动")

        # 等待 Elasticsearch
        print_step("等待 Elasticsearch 就绪...")
        for i in range(30):
            code, _ = run_command(
                f"curl -s http://localhost:{self.es_port}/_cluster/health",
                check=False,
                capture=True,
            )
            if code == 0:
                print_success("Elasticsearch 已就绪")
                return True
            print(f"  等待中... ({i + 1}/30)")
            time.sleep(2)

        print_warning("Elasticsearch 启动超时，但继续部署")
        return True

    def build_index(self) -> bool:
        """构建数据索引"""
        if self.skip_docker:
            return True

        print_header("📚 数据索引")

        index_script = self.project_dir / "index_markdown_to_es.py"
        if not index_script.exists():
            print_warning("index_markdown_to_es.py 不存在，跳过索引")
            return True

        print_step("检查索引状态...")

        # 检查索引是否存在
        code, _ = run_command(
            f"curl -s http://localhost:{self.es_port}/markdown_docs",
            check=False,
            capture=True,
        )

        if code == 0:
            print_success("索引已存在（跳过重新索引）")
            print_warning("如需重新索引，运行: python index_markdown_to_es.py --clear")
        else:
            print_step("构建 Markdown 索引（首次部署，可能需要 5-10 分钟）...")
            run_command(
                f"cd {self.project_dir} && {self.python_exe} index_markdown_to_es.py --limit 1000",
                check=False,
            )
            print_success("索引已构建")

        return True

    def start_api(self) -> bool:
        """启动 API 服务"""
        print_header("🚀 启动 API 服务")

        # 停止现有进程
        print_step("停止现有 API 进程...")
        run_command("pkill -f 'python.*search_api.py'", check=False)
        time.sleep(1)

        # 启动 API
        print_step(f"启动 API 服务 (端口 {self.api_port})...")
        api_script = self.project_dir / "search_api.py"
        if not api_script.exists():
            print_error("search_api.py 不存在")
            return False

        # 启动后台进程
        log_file = Path("/tmp/search_api.log")
        pid_file = Path("/tmp/search_api.pid")

        cmd = f"cd {self.project_dir} && {self.python_exe} search_api.py > {log_file} 2>&1 &"
        run_command(cmd)

        # 获取 PID
        time.sleep(2)
        code, output = run_command("pgrep -f 'python.*search_api.py' | head -1", capture=True)
        if code == 0:
            pid_file.write_text(output)
            print_success(f"API 服务已启动 (PID: {output})")
        else:
            print_warning("无法获取 API 进程 PID")

        return True

    def verify_deployment(self) -> None:
        """验证部署"""
        print_header("✅ 部署完成")

        print("\n📊 服务状态:\n")

        # 检查 Elasticsearch
        if not self.skip_docker:
            code, output = run_command(
                f"curl -s http://localhost:{self.es_port}/_cluster/health",
                check=False,
                capture=True,
            )
            if code == 0 and '"status":"green"' in output:
                print(f"  {Colors.GREEN}✅ Elasticsearch{Colors.ENDC}  http://localhost:{self.es_port}")
            else:
                print(f"  {Colors.YELLOW}⚠️  Elasticsearch{Colors.ENDC}  http://localhost:{self.es_port} (启动中...)")

        # 检查 API
        code, _ = run_command(
            f"curl -s http://{self.api_host}:{self.api_port}/health",
            check=False,
            capture=True,
        )
        if code == 0:
            print(f"  {Colors.GREEN}✅ Search API{Colors.ENDC}     http://localhost:{self.api_port}")
        else:
            print(f"  {Colors.RED}❌ Search API{Colors.ENDC}     http://localhost:{self.api_port}")

        print(f"\n🎯 快速开始:\n")
        print(f"  搜索示例:")
        print(f"    curl 'http://localhost:{self.api_port}/search?q=诸葛亮&mode=phrase'\n")
        print(f"  API 文档:")
        print(f"    http://localhost:{self.api_port}/docs\n")
        print(f"  查看日志:")
        print(f"    tail -f /tmp/search_api.log\n")
        print(f"  停止 API:")
        print(f"    kill $(cat /tmp/search_api.pid)\n")

        if not self.skip_docker:
            print(f"  停止 Docker:")
            print(f"    cd {self.project_dir} && docker-compose down\n")

        print(f"📖 更多信息:")
        print(f"  README:           {self.project_dir}/README.md")
        print(f"  搜索模式说明:      {self.project_dir}/SEARCH_MODES.md")
        print(f"  快速参考:         {self.project_dir}/QUICK_REFERENCE.md\n")

        print_success("部署完成！🎉\n")

    def deploy(self) -> bool:
        """执行部署"""
        try:
            if not self.pre_check():
                return False

            if not self.setup_project():
                return False

            if not self.setup_python_env():
                return False

            if not self.start_docker():
                return False

            if not self.build_index():
                return False

            if not self.start_api():
                return False

            self.verify_deployment()
            return True

        except KeyboardInterrupt:
            print_error("\n部署被中断")
            return False
        except Exception as e:
            print_error(f"部署失败: {e}")
            return False


# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="🚀 daizhigev20 一键部署脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 deploy.py
  python3 deploy.py --port 9000
  python3 deploy.py --dir /opt/daizhigev20 --port 8080
  python3 deploy.py --skip-docker
        """,
    )

    parser.add_argument(
        "--repo",
        default="https://github.com/leanderyu321-cyber/daizhigev20.git",
        help="Git 仓库地址 (默认: GitHub)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="API 服务端口 (默认: 8000)",
    )

    parser.add_argument(
        "--dir",
        default=None,
        help="项目安装目录 (默认: ~/daizhigev20)",
    )

    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="跳过 Docker 启动，仅启动 Python API",
    )

    args = parser.parse_args()

    deployer = Deployer(
        repo_url=args.repo,
        project_dir=args.dir,
        api_port=args.port,
        skip_docker=args.skip_docker,
    )

    success = deployer.deploy()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
