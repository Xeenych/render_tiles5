# Parallel tile rendering for QGIS3 #

Use QGis Script runner plugin to run render_tiles5.py

## Usage ##

 The selected object will be used for export bounds. You can edit render_tiles5.py to alter script behaviour. Tiles will be 256x256 24 bit PNG

   * minzoom - minnimum zoom level for export. Default 0

   * maxzoom - maximum zoom level for export. Default 15

   * threads - number of threads to use. Default 8

   * meta - metatile level 2 = 4x4 tiles, 3 = 8x8 tiles, 4 = 16x16 tiles and so on. Default 8

   * fileInfo - directory to store tiles



