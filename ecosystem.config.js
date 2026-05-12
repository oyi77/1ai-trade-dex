const path = require('path');
const fs = require('fs');

const ROOT = __dirname;
const FRONTEND = path.join(ROOT, 'frontend');
const VENV_PYTHON = process.platform === 'win32'
  ? path.join(ROOT, 'venv', 'Scripts', 'python.exe')
  : path.join(ROOT, 'venv', 'bin', 'python');
const LOG_DIR = path.join(ROOT, '.omc', 'logs');

if (!fs.existsSync(LOG_DIR)) {
  fs.mkdirSync(LOG_DIR, { recursive: true });
}

module.exports = {
  apps: [
    {
      name: 'polyedge-api',
      script: VENV_PYTHON,
      args: 'run.py',
      cwd: ROOT,
      interpreter: 'none',
      env: {
        PYTHONPATH: ROOT,
        DISABLE_TRADING_SCHEDULER: 'true',
      },
      env_file: path.join(ROOT, '.env'),
      watch: false,
      restart_delay: 10000,
      max_restarts: 50,
      exp_backoff_restart_delay: 100,
      wait_time: 60,
      kill_timeout: 120,
      autorestart: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(LOG_DIR, 'polyedge-api-error.log'),
      out_file: path.join(LOG_DIR, 'polyedge-api-out.log'),
    },
    {
      name: 'polyedge-frontend',
      script: process.platform === 'win32' ? 'npm.cmd' : 'npm',
      args: 'run start:prod:pm2',
      cwd: FRONTEND,
      interpreter: 'none',
      watch: false,
      restart_delay: 5000,
      max_restarts: 50,
      exp_backoff_restart_delay: 100,
      autorestart: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(LOG_DIR, 'polyedge-frontend-error.log'),
      out_file: path.join(LOG_DIR, 'polyedge-frontend-out.log'),
    },
    {
      name: 'polyedge-bot',
      script: VENV_PYTHON,
      args: '-m backend.core.orchestrator',
      cwd: ROOT,
      interpreter: 'none',
      env: {
        PYTHONPATH: ROOT,
      },
      env_file: path.join(ROOT, '.env'),
      watch: false,
      restart_delay: 5000,
      max_restarts: 50,
      exp_backoff_restart_delay: 100,
      autorestart: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: path.join(LOG_DIR, 'polyedge-bot-error.log'),
      out_file: path.join(LOG_DIR, 'polyedge-bot-out.log'),
    },
  ],
};
