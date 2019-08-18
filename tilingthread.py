# -*- coding: utf-8 -*-

#******************************************************************************
#
# QTiles
# ---------------------------------------------------------
# Generates tiles from QGIS project
#
# Copyright (C) 2012-2014 NextGIS (info@nextgis.org)
#
# This source is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# This code is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# A copy of the GNU General Public License is available on the World Wide Web
# at <http://www.gnu.org/licenses/>. You can also obtain it by writing
# to the Free Software Foundation, 51 Franklin Street, Suite 500 Boston,
# MA 02110-1335 USA.
#
#******************************************************************************
import time
import codecs
import json
from string import Template
#from PyQt5.QtCore import *
#from PyQt5.QtGui import *
import qgis.utils
from qgis.PyQt.QtGui import *
from qgis.PyQt.QtCore import *
from PyQt5.QtWidgets import QApplication
from qgis.core import *
from tile import Tile
from writers import *
from functools import partial
import threading
  

class TilingThread(QThread):
    rangeChanged = pyqtSignal(str, int)
    updateProgress = pyqtSignal()
    processFinished = pyqtSignal()
    processInterrupted = pyqtSignal()
    threshold = pyqtSignal(int)

    warring_threshold_tiles_count = 10000

    def __init__(self, layers, minZoom, maxZoom, tile_size, outputPath, rootDir, threads, tmsConvention, mbtilesCompression, jsonFile, overview, mapUrl, viewer, meta, geometry, buffers):
        QThread.__init__(self, QThread.currentThread())
        self.buffer = True
        self.threads=threads
        self.meta=meta
        self.tile_size = tile_size
        self.geometry=geometry
        self.mutex = QMutex()
        self.confirmMutex = QMutex()
        self.stopMe = 0
        self.interrupted = False
        self.layers = layers
        self.geometry_extent = self.geometry.boundingBox()
        self.geometry_extent.normalize()
        self.minZoom = minZoom
        self.maxZoom = maxZoom
        self.output = outputPath
        self.quality=-1
        self.target_crs = QgsCoordinateReferenceSystem('EPSG:3857')
        self.format='png'
        self.jobs = []
        self.sliceWriteTime=0
        if rootDir:
            self.rootDir = rootDir
        else:
            self.rootDir = 'tileset_%s' % unicode(time.time()).split('.')[0]

        self.tmsConvention = tmsConvention
        self.mbtilesCompression = mbtilesCompression
        self.jsonFile = jsonFile
        self.overview = overview
        self.mapurl = mapUrl
        self.viewer = viewer
        if self.output.isDir():
            self.mode = 'DIR'
        elif self.output.suffix().lower() == "zip":
            self.mode = 'ZIP'
        elif self.output.suffix().lower() == "ngrc":
            self.mode = 'NGM'
        elif self.output.suffix().lower() == 'mbtiles':
            self.mode = 'MBTILES'
            self.tmsConvention = True
        self.interrupted = False
        self.tiles = []
        #self.layersId = []
        #for layer in self.layers:
            #self.layersId.append(layer.id())
        #myRed = QgsProject.instance().readNumEntry('Gui', '/CanvasColorRedPart', 255)[0]
        #myGreen = QgsProject.instance().readNumEntry('Gui', '/CanvasColorGreenPart', 255)[0]
        #myBlue = QgsProject.instance().readNumEntry('Gui', '/CanvasColorBluePart', 255)[0]
        
        #image = QImage(self.tile_size, self.tile_size, QImage.Format_ARGB32_Premultiplied)
        #self.projector = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'), QgsCoordinateReferenceSystem('EPSG:3857'), QgsProject.instance().transformContext())
        #self.scaleCalc = QgsScaleCalculator()
        #self.scaleCalc.setDpi(image.logicalDpiX())
        #self.scaleCalc.setMapUnits(QgsCoordinateReferenceSystem('EPSG:3857').mapUnits())
        self.settings = QgsMapSettings()
        #self.settings.setBackgroundColor(self.color)
        #self.settings.setCrsTransformEnabled(True)
        #self.settings.setOutputDpi(image.logicalDpiX())
        #self.settings.setOutputImageFormat(QImage.Format_ARGB32_Premultiplied)
        #self.settings.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
        #self.settings.setOutputSize(image.size())
        #self.settings.setLayers(self.layers)
        #self.settings.setMapUnits(QgsCoordinateReferenceSystem('EPSG:3857').mapUnits())
        #if self.antialias:
            #self.settings.setFlag(QgsMapSettings.Antialiasing, True)
        #else:
            #self.settings.setFlag(QgsMapSettings.DrawLabeling, True)

    def run(self):
        self.mutex.lock()
        self.stopMe = 0
        self.mutex.unlock()
        self.writeLeafletViewer()
        self.writer = DirectoryWriter(self.output, self.rootDir)

        if self.jsonFile:
            self.writeJsonFile()
        if self.overview:
            self.writeOverviewFile()
        self.rangeChanged.emit(self.tr('Searching tiles...'), 0)
        useTMS = 1
        if self.tmsConvention:
            useTMS = -1

        print("Counting...")
        self.countTiles(Tile(0, 0, 0, useTMS, self.meta))
        print (len(self.tiles))

        if self.interrupted:
            del self.tiles[:]
            self.tiles = None
            self.processInterrupted.emit()
        self.rangeChanged.emit(self.tr('Rendering: %v from %m (%p%)'), len(self.tiles))

        if len(self.tiles) > self.warring_threshold_tiles_count:
            self.confirmMutex.lock()
            self.threshold.emit(self.warring_threshold_tiles_count)

        self.confirmMutex.lock()
        if self.interrupted:
            self.processInterrupted.emit()
            return

        #self.renderTiles(self.tiles)
        self.renderTilesJob2(self.tiles)

        print("Finalizing...")
        self.writer.finalize()
        if not self.interrupted:
            self.processFinished.emit()
        else:
            self.processInterrupted.emit()
        
    def stop(self):
        self.mutex.lock()
        self.stopMe = 1
        self.mutex.unlock()
        QThread.wait(self)

    def confirmContinue(self):
        self.confirmMutex.unlock()

    def confirmStop(self):
        self.interrupted = True
        self.confirmMutex.unlock()

    def writeJsonFile(self):
        filePath = '%s.json' % self.output.absoluteFilePath()
        if self.mode == 'DIR':
            filePath = '%s/%s.json' % (self.output.absoluteFilePath(), self.rootDir)
        info = {
            'name': self.rootDir,
            'format': self.format.lower(),
            'minZoom': self.minZoom,
            'maxZoom': self.maxZoom,
            'bounds': str(self.geometry_extent.xMinimum()) + ',' + str(self.geometry_extent.yMinimum()) + ',' + str(self.geometry_extent.xMaximum()) + ','+ str(self.geometry_extent.yMaximum())
        }
        with open(filePath, 'w') as f:
            f.write( json.dumps(info) )

    def writeOverviewFile(self):
        #self.settings.setExtent(self.projector.transform(self.geometry_extent))

        image = QImage(self.settings.outputSize(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        dpm = self.settings.outputDpi() / 25.4 * 1000
        image.setDotsPerMeterX(dpm)
        image.setDotsPerMeterY(dpm)

        # job = QgsMapRendererSequentialJob(self.settings)
        # job.start()
        # job.waitForFinished()
        # image = job.renderedImage()

        painter = QPainter(image)
        job = QgsMapRendererCustomPainterJob(self.settings, painter)
        job.renderSynchronously()
        painter.end()

        filePath = '%s.%s' % (self.output.absoluteFilePath(), self.format.lower())
        if self.mode == 'DIR':
            filePath = '%s/%s.%s' % (self.output.absoluteFilePath(), self.rootDir, self.format.lower())
        image.save(filePath, self.format, self.quality)

    def writeMapurlFile(self):
        filePath = '%s/%s.mapurl' % (self.output.absoluteFilePath(), self.rootDir)
        tileServer = 'tms' if self.tmsConvention else 'google'
        with open(filePath, 'w') as mapurl:
            mapurl.write('%s=%s\n' % ('url', self.rootDir + '/ZZZ/XXX/YYY.png'))
            mapurl.write('%s=%s\n' % ('minzoom', self.minZoom))
            mapurl.write('%s=%s\n' % ('maxzoom', self.maxZoom))
            mapurl.write('%s=%f %f\n' % ('center', self.geometry_extent.center().x(), self.geometry_extent.center().y()))
            mapurl.write('%s=%s\n' % ('type', tileServer))

    def writeLeafletViewer(self):
        print("writeLeafletViewer")
        templateFile = QFile(':/resources/viewer.html')
        if templateFile.open(QIODevice.ReadOnly | QIODevice.Text):
            viewer = MyTemplate(str(templateFile.readAll(), 'utf-8'))

            tilesDir = '%s/%s' % (self.output.absoluteFilePath(), self.rootDir)
            useTMS = 'true' if self.tmsConvention else 'false'
            substitutions = {
                'tilesdir': tilesDir,
                'tilesext': self.format.lower(),
                'tilesetname': self.rootDir,
                'tms': useTMS,
                'centerx': self.geometry.boundingBox().center().x(),
                'centery': self.geometry.boundingBox().center().y(),
                'avgzoom': (self.maxZoom + self.minZoom) / 2,
                'maxzoom': self.maxZoom
            }

            filePath = '%s/%s.html' % (self.output.absoluteFilePath(), self.rootDir)
            print (filePath)
            with codecs.open(filePath, 'w', 'utf-8') as fOut:
                fOut.write(viewer.substitute(substitutions))
            templateFile.close()

    def countTiles(self, tile):
        print ("TilingThread.countTiles")
        #prj = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:3395'), QgsCoordinateReferenceSystem('EPSG:4326'), QgsProject.instance().transformContext())
        geometry_extent = self.geometry.boundingBox()
        geometry_extent.normalize()
        tile_extent = tile.toRectangle()
        tile_geom =  QgsGeometry.fromRect(tile_extent)
        if (not self.geometry.intersects(tile_geom)):
            print ("skipping")
            return
        if self.interrupted:
            return
        
        #if (not self.geometry_extent.intersects(tile.toRectangle())):
            #return

        #if self.minZoom <= tile.z and tile.z <= self.maxZoom:
            #if not self.renderOutsideTiles:
                #for layer in self.layers:
                    #if layer.extent().intersects(tile.toRectangle()):
                        #self.tiles.append(tile)
                        #break
            #else:
                #self.tiles.append(tile)
        if self.minZoom <= tile.z and tile.z <= self.maxZoom:
            self.tiles.append(tile)
        if tile.z < self.maxZoom:
            for x in range(2 * tile.x, 2 * (tile.x + self.meta), self.meta):
                for y in range(2 * tile.y, 2 * (tile.y + self.meta), self.meta):
                    self.mutex.lock()
                    s = self.stopMe
                    self.mutex.unlock()
                    if s == 1:
                        self.interrupted = True
                        return
                    subTile = Tile(x, y, tile.z + 1, tile.tms, self.meta)
                    self.countTiles(subTile)

    def renderTiles(self, tiles):
        cnt=0
        for t in tiles:
            print('Rendering tile ', cnt, 'from ', len(tiles), ' z=', t.z,' x= ', t.x,' y= ' ,t.y )
            cnt=cnt+1
            self.render(t)
            self.updateProgress.emit()
            self.mutex.lock()
            s = self.stopMe
            self.mutex.unlock()
            if s == 1:
                self.interrupted = True
                break 

#РќР° СЂР°Р±РѕС‚Рµ QGIS 3.4.3
# z10-z15, 229 tiles, 1 sheet @4cpu = 502
# z10-z15, 229 tiles, 1 sheet @3cpu = 541
# z10-z15, 229 tiles, 1 sheet @2cpu = 738
# z10-z15, 229 tiles, 1 sheet @1cpu = 1416

# z10-z15, 410 tiles, 2 sheet @4cpu = 
# z10-z15, 410 tiles, 2 sheet @3cpu = 971
# z10-z15, 410 tiles, 2 sheet @2cpu = 1330
# z10-z15, 410 tiles, 2 sheet @1cpu = 2518

#РќР° СЂР°Р±РѕС‚Рµ QGIS 3.6
# z10-z15, 229 tiles, 1 sheet @3cpu = 562
# z10-z15, 410 tiles, 2 sheet @3cpu = 1016
# z10-z15, 594 tiles, 3 sheet @3cpu = 1345

#РґРѕРјР° QGIS 3.6
# z10-z15, 229 tiles, 1 sheet @1cpu = 
# z10-z15, 229 tiles, 1 sheet @2cpu = 748
# z10-z15, 229 tiles, 1 sheet @3cpu = 512
# z10-z15, 229 tiles, 1 sheet @4cpu = 396
# z10-z15, 229 tiles, 1 sheet @5cpu = 331
# z10-z15, 229 tiles, 1 sheet @6cpu = 319
# z10-z15, 229 tiles, 1 sheet @7cpu = 263 (302, SMT 16 Gb)
# z10-z15, 229 tiles, 1 sheet @8cpu = 280 (324, SMT 16 Gb)
# z10-z15, 229 tiles, 1 sheet @10cpu = (264, SMT 16 Gb) 
# z10-z15, 229 tiles, 1 sheet @12cpu = (260, SMT 16 Gb) 
# z10-z15, 229 tiles, 1 sheet @16cpu = (256, SMT 16 Gb) 
#231

# z10-z15, Terskey 8621t, @8CPU, SMT, meta2 = 11086
# z10-z15, Terskey 2276t, @8CPU, SMT, meta3 = 7067

#http://planet.qgis.org/planet/tag/pyqt/
    def renderTilesJob2(self, tiles):
        cnt=0
        length = len(tiles)
        while len(tiles)>0:
            if (len(self.jobs)<self.threads):
                t = tiles.pop(0)
                cnt=cnt+1
                print('Rendering tile ', cnt, 'from ', length, ' z=', t.z,' x= ', t.x,' y= ' ,t.y )
                j,t = self.renderJob(t)        
                self.jobs.append((j,t))
                j.start()
            else:
                QApplication.processEvents()
 
        for j,t in self.jobs:
            j.waitForFinished()
            

    def onJobFinish(self, job, tile):
        #print (threading.get_ident())
        self.jobs.remove((job,tile))
        image = job.renderedImage()
        start = time.time()
        self.slice(image, tile)
        #self.writer.writeTile(tile, image, 'png', -1)
        end = time.time()
        ttt = end-start
        #print ("SliceWrite= ", ttt)
        self.sliceWriteTime = self.sliceWriteTime + ttt


    def renderJob(self, tile):
        prj = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'), self.target_crs, QgsProject.instance().transformContext())
        if self.buffer:
            ex = tile.toRectangleBuffered();
            self.settings.setOutputSize(QSize(self.tile_size * (tile.meta + 2), self.tile_size * (tile.meta + 2)))
        else:
            ex = tile.toRectangle();
            self.settings.setOutputSize(QSize(self.tile_size * (tile.meta), self.tile_size * (tile.meta)))
        self.settings.setDestinationCrs(self.target_crs)
        self.settings.setTransformContext(QgsProject.instance().transformContext())
        self.settings.setExtent(prj.transform(ex))
        self.settings.setLayers(self.layers)
        self.settings.setBackgroundColor(QColor("transparent"))  

        self.settings.setFlag(QgsMapSettings.Antialiasing, True)
        self.settings.setFlag(QgsMapSettings.DrawEditingInfo, False)
        self.settings.setFlag(QgsMapSettings.ForceVectorOutput, True)
        self.settings.setFlag(QgsMapSettings.UseAdvancedEffects, False)
        self.settings.setFlag(QgsMapSettings.DrawLabeling, True)
        self.settings.setFlag(QgsMapSettings.UseRenderingOptimization, True) #true - Р Р…Р ВµР СР Р…Р С•Р С–Р С• Р В±РЎвЂ№РЎРѓРЎвЂљРЎР‚Р ВµР Вµ
        self.settings.setFlag(QgsMapSettings.DrawSelection, False)
        self.settings.setFlag(QgsMapSettings.DrawSymbolBounds, False)
        self.settings.setFlag(QgsMapSettings.RenderMapTile, True)

        #self.settings.setOutputImageFormat(QImage.Format_ARGB32) #479
        self.settings.setOutputImageFormat(QImage.Format_ARGB32_Premultiplied) #332
        #self.settings.setOutputImageFormat(QImage.Format_Indexed8)

        #self.settings.setOutputDpi(300)
        labelsettings = QgsLabelingEngineSettings()
        labelsettings.setFlag(QgsLabelingEngineSettings.UseAllLabels, False)
        labelsettings.setFlag(QgsLabelingEngineSettings.UsePartialCandidates, False)
        labelsettings.setFlag(QgsLabelingEngineSettings.RenderOutlineLabels, False)
        labelsettings.setFlag(QgsLabelingEngineSettings.DrawLabelRectOnly, False)
        labelsettings.setFlag(QgsLabelingEngineSettings.DrawCandidates, False)
        self.settings.setLabelingEngineSettings(labelsettings)

        #job = QgsMapRendererSequentialJob(self.settings)
        #job.start()
        #job.waitForFinished() 
        #image = job.renderedImage()

        job = QgsMapRendererParallelJob(self.settings)
        job.finished.connect(partial(self.onJobFinish, job, tile))
        #job.start()
        return job, tile

    def render(self, tile):
        # scale = self.scaleCalc.calculate(
        #    self.projector.transform(tile.toRectangle()), self.width)
        #print("TilingThread.render")
        prj = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:4326'), self.target_crs, QgsProject.instance().transformContext())
        ex = tile.toRectangle();
        self.settings.setDestinationCrs(self.target_crs)
        self.settings.setTransformContext(QgsProject.instance().transformContext())
        self.settings.setExtent(prj.transform(ex))
        self.settings.setLayers(self.layers)
        self.settings.setOutputSize(QSize(self.tile_size * (tile.meta), self.tile_size * (tile.meta)))
        self.settings.setBackgroundColor(QColor("transparent"))  

        self.settings.setFlag(QgsMapSettings.Antialiasing, True)
        self.settings.setFlag(QgsMapSettings.DrawEditingInfo, False)
        self.settings.setFlag(QgsMapSettings.ForceVectorOutput, True)
        self.settings.setFlag(QgsMapSettings.UseAdvancedEffects, False)
        self.settings.setFlag(QgsMapSettings.DrawLabeling, True)
        self.settings.setFlag(QgsMapSettings.UseRenderingOptimization, True) #true - Р Р…Р ВµР СР Р…Р С•Р С–Р С• Р В±РЎвЂ№РЎРѓРЎвЂљРЎР‚Р ВµР Вµ
        self.settings.setFlag(QgsMapSettings.DrawSelection, False)
        self.settings.setFlag(QgsMapSettings.DrawSymbolBounds, False)
        self.settings.setFlag(QgsMapSettings.RenderMapTile, True)



        #self.settings.setOutputImageFormat(QImage.Format_ARGB32) #479
        self.settings.setOutputImageFormat(QImage.Format_ARGB32_Premultiplied) #332
        #self.settings.setOutputImageFormat(QImage.Format_Indexed8)

        #self.settings.setOutputDpi(300)
        labelsettings = QgsLabelingEngineSettings()
        labelsettings.setFlag(QgsLabelingEngineSettings.UseAllLabels, False)
        labelsettings.setFlag(QgsLabelingEngineSettings.UsePartialCandidates, False)
        labelsettings.setFlag(QgsLabelingEngineSettings.RenderOutlineLabels, False)
        labelsettings.setFlag(QgsLabelingEngineSettings.DrawLabelRectOnly, False)
        labelsettings.setFlag(QgsLabelingEngineSettings.DrawCandidates, False)
        self.settings.setLabelingEngineSettings(labelsettings)

        #job = QgsMapRendererSequentialJob(self.settings)
        #job.start()
        #job.waitForFinished() 
        #image = job.renderedImage()

        job = QgsMapRendererParallelJob(self.settings)
        job.start()
        job.waitForFinished() 
        image = job.renderedImage()


        #image = QImage(self.settings.outputSize(), QImage.Format_ARGB32)
        #painter = QPainter(image)
        #job = QgsMapRendererCustomPainterJob(self.settings, painter)
        #job.renderSynchronously()
        #painter.end()

        #if (self.format=='png'):
        #image = image.convertToFormat(QImage.Format_Indexed8)


        #image=image.copy(self.width * (2**self.meta) * (factor-1.0)/2.0, self.height* (2**self.meta) * (factor-1.0)/2.0 ,self.width * (2**self.meta), self.height* (2**self.meta))
        #print("TilingThread.slice")
        
        self.slice(image, tile)
        #newImage = image.convertToFormat(QImage.Format_Indexed8, Qt.ThresholdDither|Qt.NoOpaqueDetection)
        #self.writer.writeTile(tile, image, 'png', -1)
        #del image
        #del painter

    def slice(self, meta_img, metatile):
        #print("TilingThread.Slice")
        #  get the tile range within this metatile (filtering outside tiles if buffered)
        if self.buffer:
            offset = 1
        else:
            offset = 0
        x_min = offset
        y_min = offset
        x_max = metatile.meta + offset
        y_max = metatile.meta + offset

        #  loop through the tiles in the metatile and crop the metatile to the tile.
        #print ('slice', x_min, x_max, y_min, y_max)
        for x in range(x_min, x_max):
            for y in range(y_min, y_max):
                #print ("xy", x, y)
                #  get the top-left location (in pixels) of the tile to be extracted from the metatile.
                #  crop the loaded metatile to the tile
                new_img = meta_img.copy(x *  self.tile_size, y * self.tile_size, self.tile_size, self.tile_size)
                    #  get the tile number (x and y)
                tile_x =  metatile.x + x - offset
                tile_y =  metatile.y + y - offset
                #  create a Tile instance
                tile = Tile(tile_x, tile_y, metatile.z)
                #  use the selected writer to write the file

                #if (self.geometry.intersects(tile.toRectangle())):
                self.writer.writeTile(tile, new_img, self.format, self.quality)

                #  destroy the tile in memory - just in case.
                del new_img
        #  destroy the metatile just in case.
        del meta_img

class MyTemplate(Template):
    delimiter = '@@'

    def __init__(self, templateString):
        Template.__init__(self, templateString)
