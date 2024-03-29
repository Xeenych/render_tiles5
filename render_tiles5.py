from qgis.core import *
import qgis.utils
import os
import time
from qgis.PyQt.QtGui import *
from qgis.PyQt.QtCore import *
import tilingthread

# 12221 sec - all terskeyf

def run_script(iface):
    start = time.time()
    
    #layers = utils.getMapLayers()
    layers = iface.mapCanvas().layers()


#	layerMap = QgsMapLayerRegistry.instance().mapLayers()
#	for name, layer in layerMap.iteritems():
#		if (layer.name()=='bounds'):
#			ext_layer=layer

    ext_layer = qgis.utils.iface.activeLayer()
    crs = ext_layer.crs()
    selected_features = ext_layer.selectedFeatures()
    projector = QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem('EPSG:4326'), QgsProject.instance().transformContext())
    print (ext_layer)



#terskey raster tree + raster dem
#meta8 z0-z15 2292 tiles = 4529; 2078

#sheet+barren
#meta8 z0-z15 80 tiles = 405, 168
#sheet-barren 
#meta8 z0-z15 80 tiles = 231, 100

    # !!!! allow truncated lables = True !!!!

    fileInfo = QFileInfo("d:\\12 - QGIS\\web_test\\")  # directory to store tiles
    filename = "mapnik" # filename
    minzoom=0
    maxzoom=15
    meta=8 # metatile level 2 = 4x4 tiles, 3 = 8x8 tiles, 4 = 16x16 tiles and so on
    threads = 8 # number of threads to use
    mbtiles=False
    buffers=1


    geometry = selected_features[0].geometry()
    for i in selected_features:
        geometry=geometry.combine(i.geometry())
        print (geometry)

    geometry.transform(projector)


    worker = tilingthread.TilingThread(layers, minzoom, maxzoom, 256, fileInfo, filename, threads, 0, mbtiles,0,0,0,1, meta, geometry, buffers)
    print ("running")
    worker.run()
        #worker.start() #in another thread
        #worker.wait()
    print ("FINISH")
    end = time.time()
    print ("Total time ", end - start)
    print ("SliceWriteTime ", worker.sliceWriteTime)