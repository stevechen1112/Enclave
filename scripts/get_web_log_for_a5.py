#!/usr/bin/env python3
"""Fetch web logs around the A5 timeframe to detect chat errors/timeouts."""
import paramiko

HOST = "172.237.5.254"
KEY_FILE = "C:/Users/User/.ssh/id_rsa_linode"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username="root", key_filename=KEY_FILE, timeout=30)

cmd = "docker logs aihr-web --since 50m --tail 400"
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
print(stdout.read().decode())
err = stderr.read().decode().strip()
if err:
    print(err)

ssh.close()
