#!/usr/bin/env python3
"""
Upload SSH public key to remote server using password authentication
"""
import sys
import os

try:
    import paramiko
except ImportError:
    print("❌ paramiko not installed. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

def upload_ssh_key(host, username, password, public_key_path):
    """Upload SSH public key using password authentication"""
    
    print(f"🔐 Connecting to {username}@{host}...")
    
    try:
        # Read local public key
        with open(public_key_path, 'r') as f:
            pub_key = f.read().strip()
        
        # Create SSH client
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Connect with password
        client.connect(
            hostname=host,
            username=username,
            password=password,
            timeout=10
        )
        
        print("✅ Connected successfully!")
        print("📤 Uploading SSH public key...")
        
        # Create .ssh directory and upload key
        commands = [
            "mkdir -p ~/.ssh",
            "chmod 700 ~/.ssh",
            f"echo '{pub_key}' >> ~/.ssh/authorized_keys",
            "chmod 600 ~/.ssh/authorized_keys",
            "sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys",  # Remove duplicates
            "echo 'SSH_KEY_UPLOAD_SUCCESS'"
        ]
        
        combined_command = " && ".join(commands)
        stdin, stdout, stderr = client.exec_command(combined_command)
        
        output = stdout.read().decode()
        error = stderr.read().decode()
        
        if "SSH_KEY_UPLOAD_SUCCESS" in output:
            print("✅ SSH key uploaded successfully!")
            print("\n🔑 Testing passwordless login...")
            
            # Test passwordless login
            test_client = paramiko.SSHClient()
            test_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            try:
                # Try to connect with key (no password)
                key_path = public_key_path.replace('.pub', '')
                pkey = paramiko.RSAKey.from_private_key_file(key_path)
                test_client.connect(
                    hostname=host,
                    username=username,
                    pkey=pkey,
                    timeout=5
                )
                
                stdin, stdout, stderr = test_client.exec_command("echo 'Passwordless login verified!'")
                result = stdout.read().decode().strip()
                print(f"✅ {result}")
                
                test_client.close()
                client.close()
                return True
                
            except Exception as e:
                print(f"⚠️  Passwordless login test failed: {e}")
                print("    But key was uploaded. Please test manually.")
                client.close()
                return True
        else:
            print(f"❌ Upload failed: {error}")
            client.close()
            return False
            
    except paramiko.AuthenticationException:
        print("❌ Authentication failed! Please check password.")
        return False
    except paramiko.SSHException as e:
        print(f"❌ SSH error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Upload SSH public key to remote server')
    parser.add_argument('host', help='Remote host IP or hostname')
    parser.add_argument('username', help='Remote username')
    parser.add_argument('password', help='Remote password')
    parser.add_argument('--key', default=os.path.expanduser('~/.ssh/id_rsa_linode.pub'),
                       help='Path to public key file')
    
    args = parser.parse_args()
    
    success = upload_ssh_key(args.host, args.username, args.password, args.key)
    sys.exit(0 if success else 1)
