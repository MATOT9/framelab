# FrameLab native backend scaffold v2

This package contains:

- grouped decode-family implementation for Mono and Bayer raw formats
- a generic first-pass metrics kernel
- raw loader and TIFF hook separation
- sample raw files with known visual features and manifest metadata
- a small CLI demo target for native-backend-only testing

## Build

```bash
cd native
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

## Demo CLI

```bash
./native/build/fl_metrics_demo sample_data/raw/mono12p_scene.raw mono12p 128 96 192 out_preview.pgm
```

The final optional argument writes an 8-bit PGM preview so you can inspect whether decode shape/features are correct.
