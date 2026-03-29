# Sample raw files

Each raw file represents the same logical grayscale scene:

- bright outer border
- two diagonals forming an X
- central crosshair
- four quadrant intensity blocks
- horizontal stripe pattern near the bottom
- a bright filled disk in the lower-right area

These features make decode errors easy to spot:

- wrong packing usually breaks the diagonals/stripe band
- wrong byte order changes quadrant levels
- wrong stride typically shears or tears the image across rows

Use `manifest.csv` for width/height/stride/pixel format, and compare output to the PNG preview in `sample_data/previews/`.
