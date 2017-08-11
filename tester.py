# The MIT License (MIT)
#
# Copyright (c) 2017 Scott Shawcroft for Adafruit Industries
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import os
import redis
import serial
from serial.tools import list_ports
import sh
import shutil
import time
import storage

redis = redis.Redis()

def redis_log(key, message):
    redis.append(key, message)

def run_circuitpython_tests(log_key, board_name, test_env, mountpoint, serial_connection, tests):
    # Get into the REPL and disable autoreload.
    serial_connection.write(b'\x03\x03')
    serial_connection.reset_input_buffer()
    serial_connection.write(b"import samd\r")
    serial_connection.write(b"samd.disable_autoreload()\r")
    time.sleep(0.1)
    output = serial_connection.read(serial_connection.in_waiting)
    if not output.endswith(b"samd.disable_autoreload()\r\n>>> "):
        redis_log(log_key, output)
        raise RuntimeError("Unable to enter the REPL.")

    test_files = []
    if "test_directories" in tests:
        for directory in tests["test_directories"]:
            for fn in os.listdir(directory):
                if fn.endswith(".py"):
                    test_files.append(directory + "/" + fn)

    with open(mountpoint + "/test_env.py", "w") as f:
        f.write("board = {0}\n".format(repr(board_name)))
        if test_env:
            for key in test_env:
                f.write("{0} = {1}\n".format(key, repr(test_env[key])))

    if "test_helper" in tests:
        for filename in tests["test_helper"]:
            if os.path.isfile(filename):
                shutil.copy(filename, mountpoint + "/")
            else:
                redis_log(log_key, "Unable to find test helper: {0}\n".format(filename))

    tests_ok = True
    outcome = {"passed": 0, "skipped": 0, "failed": 0, "crashed": 0, "timed out": 0}
    for test_file in test_files:
        if os.path.isfile(test_file + ".exp"):
            continue

        shutil.copy(test_file, mountpoint + "/code.py")
        os.sync()
        time.sleep(0.05)

        serial_connection.reset_input_buffer()
        serial_connection.write(b"\x04")
        output = b""
        safe_mode = False
        start_time = time.monotonic()
        while not output.endswith(b"Use CTRL-D to reload.\r\n") and time.monotonic() - start_time < 10:
            try:
                if serial_connection.in_waiting > 0:
                    output += serial_connection.read(serial_connection.in_waiting)
                else:
                    time.sleep(0.05)
            except OSError as e:
                # We get OSError if our USB dies from safe mode.
                safe_mode = True
                break

        if safe_mode:
            redis_log(log_key, test_file + " crashed on " + board_name + "!\n" + output.decode("utf-8") + "\n")
            tests_ok = False
            outcome["crashed"] += 1
            # TODO(tannewt): Recover out of safe mode and continue tests.
            break
        elif not output.endswith(b"Use CTRL-D to reload.\r\n"):
            redis_log(log_key, test_file + " timed out on " + board_name + ":\n" + output.decode("utf-8") + "\n")
            serial_connection.write(b'\x03\x03')
            tests_ok = False
            outcome["timed out"] += 1
        elif b"Traceback (most recent call last):" in output:
            redis_log(log_key, test_file + " threw an exception on " + board_name + ":\n" + output.decode("utf-8") + "\n")
            tests_ok = False
            outcome["failed"] += 1
        elif b"SKIP" in output:
            outcome["skipped"] += 1
        else:
            outcome["passed"] += 1
    test_outcomes = "; ".join([str(outcome[x]) + " tests " + x for x in sorted(outcome.keys())])
    test_outcomes += " on board " + board_name + ".\n"
    redis_log(log_key, test_outcomes)
    return tests_ok

def run_tests(board, binary, tests, log_key=None):
    serial_device_name = None
    for port in list_ports.comports():
        if port.location and port.location[2:] == board["path"]:
            serial_device_name = port.name
    if not serial_device_name:
        raise RuntimeError("Board not found at path: " + board["path"])

    bootloader = board["bootloader"]
    tests_ok = True

    with redis.lock("lock:device@" + board["path"], timeout=60*20) as lock:
        # Trigger the bootloader.
        if bootloader in ("uf2", "samba"):
            s = serial.Serial("/dev/" + serial_device_name, 1200)
            s.close()

        time.sleep(5)

        if bootloader == "uf2":
            # Mount the filesystem.
            disk_path = None
            for disk in os.listdir("/dev/disk/by-path"):
                if board["path"] in disk:
                    disk_path = disk
            if not disk_path:
                raise RuntimeError("Disk not found for board: " + board["path"])
            
            disk_path = "/dev/disk/by-path/" + disk_path
            if os.path.isfile(disk_path + "-part1"):
                raise RuntimeError("MCU not in bootloader because part1 exists.")

            sh.pmount(disk_path, "fs-" + board["path"])
            mountpoint = "/media/fs-" + board["path"]
            redis_log(log_key, "Successfully mounted UF2 bootloader at {0}\n".format(mountpoint))
            with open(mountpoint + "/INFO_UF2.TXT", "r") as f:
                redis_log(log_key, f.read() + "\n")
            shutil.copy(binary, mountpoint)
            # Unmount the mountpoint in case the device has disappeared already after the UF2
            # was flashed.
            sh.pumount(mountpoint)

        if "circuitpython_tests" in tests:
            # First find our CircuitPython disk.
            start_time = time.monotonic()
            disk_path = None
            while not disk_path and time.monotonic() - start_time < 10:
                for disk in os.listdir("/dev/disk/by-path"):
                    if board["path"] in disk and disk.endswith("part1"):
                        disk_path = disk
            if not disk_path:
                raise RuntimeError("Cannot find CIRCUITPY disk for device: " + board["path"])

            disk_path = "/dev/disk/by-path/" + disk_path

            with storage.mount(storage.NativeFileSystem(disk_path), "/media/cpy-" + board["path"]):
                mountpoint = "/media/cpy-" + board["path"]
                redis_log(log_key, "Successfully mounted CIRCUITPY disk at {0}\n".format(mountpoint))

                # Now find the serial.
                serial_device_name = None
                for port in list_ports.comports():
                    if port.location and port.location[2:] == board["path"]:
                        serial_device_name = port.name
                if not serial_device_name:
                    raise RuntimeError("No CircuitPython serial connection found at path: " + board["path"])
                with serial.Serial("/dev/" + serial_device_name) as conn:
                    tests_ok = run_circuitpython_tests(log_key, board["board"], board["test_env"], mountpoint, conn, tests["circuitpython_tests"]) and tests_ok


    return tests_ok

if __name__ == "__main__":
    pass
