# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import subprocess
import time
import tempfile
import shutil

def test_relocation_logging():
    with tempfile.TemporaryDirectory(prefix="blindrss_reloc_") as tmpdir:
        # Simulate install dir
        install_dir = os.path.join(tmpdir, "install")
        os.makedirs(install_dir)
        
        # Copy helper to install dir to trigger relocation
        helper_in_install = os.path.join(install_dir, "update_helper.bat")
        shutil.copy2("update_helper.bat", helper_in_install)
        
        staging_dir = os.path.join(tmpdir, "staging")
        os.makedirs(staging_dir)
        
        exe_name = "BlindRSS.exe"
        with open(os.path.join(install_dir, exe_name), "w") as f:
            f.write("old")
        with open(os.path.join(staging_dir, exe_name), "w") as f:
            f.write("new")
            
        # Mock PID
        proc = subprocess.Popen(["cmd", "/c", "timeout /t 1"], stdout=subprocess.DEVNULL)
        pid = proc.pid
        
        cmd = [
            "cmd.exe", "/c", helper_in_install,
            str(pid),
            install_dir,
            staging_dir,
            exe_name,
            "", # temp_root
            ""  # show_log
        ]
        
        print("Running relocation test...")
        temp_before = set(os.listdir(tempfile.gettempdir()))
        
        # Run it
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(f"First process exit code: {result.returncode}")
        
        # Wait for the relocated process to finish
        time.sleep(5)
        
        temp_after = set(os.listdir(tempfile.gettempdir()))
        new_files = temp_after - temp_before
        log_files = [f for f in new_files if f.startswith("BlindRSS_update_") and f.endswith(".log")]
        
        if log_files:
            print(f"FAILURE: Log files found: {log_files}")
            for lf in log_files:
                lpath = os.path.join(tempfile.gettempdir(), lf)
                with open(lpath, "r") as f:
                    print(f"--- Content of {lf} ---")
                    print(f.read())
                try: os.remove(lpath)
                except: pass
        else:
            print("SUCCESS: No log files left behind.")

if __name__ == "__main__":
    test_relocation_logging()
