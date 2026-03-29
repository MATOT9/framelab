# Building the Python extension module

This backend can now build a real Python extension module named `_native`.

## What gets produced

- Windows: `_native.pyd`
- Linux: `_native.so`

By default the output is placed in:

```text
framelab/native/
```

so it can be imported directly by:

```python
from framelab.native import _native
```

## Requirements

- CMake 3.21+
- A Python installation with development headers
- NumPy installed in that same Python environment

## Configure and build

### Visual Studio / MSVC

```bat
cmake -S native -B native\build -DFRAMELAB_BUILD_PYTHON_MODULE=ON
cmake --build native\build --config Release -j
```

### Ninja / Linux

```bash
cmake -S native -B native/build -G Ninja -DFRAMELAB_BUILD_PYTHON_MODULE=ON -DCMAKE_BUILD_TYPE=Release
cmake --build native/build -j
```

## Important note about Python environment selection

CMake will locate a Python interpreter and its development files. Make sure you
configure with the same Python environment that will import the extension.

If needed, point CMake explicitly at the interpreter:

```bash
cmake -S native -B native/build -DPython3_EXECUTABLE=/path/to/python
```

## Optional output override

The default output location is the package folder. You can override it:

```bash
cmake -S native -B native/build -DFRAMELAB_PYTHON_OUTPUT_DIR=/custom/output/path
```
