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

import sh

class NativeFileSystem:
    def __init__(self, device_path):
        self.device_path = device_path

class AutoUnmount:
    def __init__(self, mount_point):
        self.mount_point = mount_point

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        sh.pumount(self.mount_point)
        return False

def mount(fs, mount_point):
    if not isinstance(fs, NativeFileSystem):
        raise ValueError("Only NativeFileSystems are supported on Raspberry Pi.")

    sh.pmount("-tvfat", fs.device_path, mount_point)
    return AutoUnmount(mount_point)

