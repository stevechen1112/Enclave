#!/usr/bin/env python3
"""Deploy chat fixes to the cloud and rebuild web/worker containers."""
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

LOCAL_FILES = {
    "C:/Users/User/Desktop/aihr/app/services/structured_answers.py": "/opt/aihr/app/services/structured_answers.py",
    "C:/Users/User/Desktop/aihr/app/services/chat_orchestrator.py": "/opt/aihr/app/services/chat_orchestrator.py",
}

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)

sftp = ssh.open_sftp()
for local_path, remote_path in LOCAL_FILES.items():
    sftp.put(local_path, remote_path)
    print(f"Uploaded {local_path} -> {remote_path}")

sftp.close()

cmd = "cd /opt/aihr && docker compose -f docker-compose.minimal.yml up -d --build gateway web worker"
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=900)
print(stdout.read().decode().strip())
err = stderr.read().decode().strip()
if err:
    print(err)

ssh.close()
