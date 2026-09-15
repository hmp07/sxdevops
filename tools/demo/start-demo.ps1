# SxDevOps 离线演示一键启动脚本（Windows + Docker Desktop）
#
# 用法（PowerShell）:
#   .\start-demo.ps1                    # 使用同目录下的 sxdevops-demo.tar
#   .\start-demo.ps1 -ImageTar D:\demo\sxdevops-demo.tar -Port 8000
#
# 流程: 检查 Docker → docker load 镜像 → 清理旧容器 → 启动 → 等待就绪 → 打开浏览器

param(
    [string]$ImageTar = "$PSScriptRoot\sxdevops-demo.tar",
    [string]$ImageName = "sxdevops-demo:latest",
    [string]$ContainerName = "sxdevops-demo",
    [int]$Port = 8000,
    [switch]$ResetData
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host "[SxDevOps Demo] $msg" -ForegroundColor Cyan
}

function Write-Error-Step([string]$msg) {
    Write-Host "[SxDevOps Demo] 错误: $msg" -ForegroundColor Red
}

Write-Step "检查 Docker 环境..."
try {
    docker version --format '{{.Server.Version}}' 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Step "未检测到 Docker。请先安装 Docker Desktop 并启动。"
        Write-Host "下载地址: https://www.docker.com/products/docker-desktop/" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Error-Step "无法执行 docker 命令: $($_.Exception.Message)"
    exit 1
}
Write-Step "Docker 已就绪。"

# 检查端口占用
$portInUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Error-Step "端口 $Port 已被占用（PID: $($portInUse.OwningProcess)）。"
    Write-Host "可使用 -Port 参数更换端口，例如: .\start-demo.ps1 -Port 8001" -ForegroundColor Yellow
    exit 1
}

# 加载镜像（已存在则跳过）
$imageExists = docker images -q $ImageName 2>$null
if (-not $imageExists) {
    if (-not (Test-Path $ImageTar)) {
        Write-Error-Step "找不到镜像包: $ImageTar"
        Write-Host "请将 sxdevops-demo.tar 与本脚本放在同一目录，或使用 -ImageTar 指定路径。" -ForegroundColor Yellow
        exit 1
    }
    Write-Step "导入镜像（首次约 1-2 分钟）..."
    docker load -i $ImageTar
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Step "镜像导入失败。"
        exit 1
    }
    Write-Step "镜像导入完成。"
} else {
    Write-Step "镜像已存在，跳过导入。"
}

# 清理旧容器
$existing = docker ps -a -q -f "name=^/$ContainerName$" 2>$null
if ($existing) {
    Write-Step "清理旧容器..."
    docker rm -f $ContainerName 2>&1 | Out-Null
}

# 如需重置演示数据（恢复初始演示状态）
$volumeArgs = @("-v", "${ContainerName}_data:/data")
if ($ResetData) {
    Write-Step "重置演示数据卷..."
    docker volume rm "${ContainerName}_data" 2>&1 | Out-Null
}

# 启动容器
Write-Step "启动演示容器..."
docker run -d `
    --name $ContainerName `
    --restart unless-stopped `
    -p "${Port}:8000" `
    @volumeArgs `
    -e DATABASE_ENGINE=sqlite `
    -e SQLITE_NAME=/data/db.sqlite3 `
    -e SQLITE_TIMEOUT=20 `
    -e SXDEVOPS_WAIT_FOR_DB=0 `
    -e SXDEVOPS_MIGRATE=1 `
    -e SXDEVOPS_SEED_DATA=1 `
    -e SXDEVOPS_SEED_TEMPLATES=1 `
    -e SXDEVOPS_DEMO_MODE=1 `
    -e DEEPAGENTS_FALLBACK_ON_ERROR=0 `
    -e SECRET_KEY=sxdevops-offline-demo `
    -e DEBUG=0 `
    -e ALLOWED_HOSTS='*' `
    -e CORS_ALLOW_ALL_ORIGINS=1 `
    $ImageName

if ($LASTEXITCODE -ne 0) {
    Write-Error-Step "容器启动失败，请检查上方 docker 输出。"
    exit 1
}

# 等待就绪（首次启动需执行迁移 + 种子数据，约 30-90 秒）
Write-Step "等待服务就绪（首次启动约 30-90 秒）..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$Port" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        # 服务尚未就绪，继续等待
    }
    if (($i % 10) -eq 0) {
        Write-Step "仍在启动中... ($($i * 2)s)"
    }
}

if (-not $ready) {
    Write-Error-Step "等待超时。请运行 docker logs $ContainerName 查看日志。"
    exit 1
}

Write-Step "演示环境已就绪！" -ForegroundColor Green
Write-Host ""
Write-Host "  访问地址: http://localhost:$Port" -ForegroundColor Green
Write-Host "  登录账号: admin" -ForegroundColor Green
Write-Host "  登录密码: Admin@123456" -ForegroundColor Green
Write-Host ""
Write-Host "  常用操作:" -ForegroundColor Yellow
Write-Host "    查看日志: docker logs -f $ContainerName"
Write-Host "    停止演示: docker stop $ContainerName"
Write-Host "    恢复初始数据: docker stop $ContainerName; docker volume rm ${ContainerName}_data; .\start-demo.ps1"
Write-Host ""

# 打开浏览器
Start-Process "http://localhost:$Port"
Write-Step "已打开浏览器。"
