# -*- coding: utf-8 -*-

# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2019 sliptonic <shopinthewoods@gmail.com>               *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import FreeCAD
import Part
import PathScripts.PathGeom as PathGeom
import PathScripts.PathLog as PathLog
import PathScripts.PathSetupSheetOpPrototype as PathSetupSheetOpPrototype
import PathScripts.PathUtil as PathUtil
import PySide
import Sketcher
import math
import zipfile

__title__ = "Tool bits."
__author__ = "sliptonic (Brad Collette)"
__url__ = "http://www.freecadweb.org"
__doc__ = "Class to deal with and represent a tool bit."

PathLog.setLevel(PathLog.Level.DEBUG, PathLog.thisModule())
PathLog.trackModule()

def translate(context, text, disambig=None):
    return PySide.QtCore.QCoreApplication.translate(context, text, disambig)

ParameterTypeConstraint = {
        'Angle':        'App::PropertyAngle',
        'Distance':     'App::PropertyLength',
        'DistanceX':    'App::PropertyLength',
        'DistanceY':    'App::PropertyLength',
        'Radius':       'App::PropertyLength'
        }


def updateConstraint(sketch, name, value):
    for i, constraint in enumerate(sketch.Constraints):
        if constraint.Name.split(';')[0] == name:
            if constraint.Type in ['DistanceX', 'DistanceY', 'Distance', 'Radius']:
                if not PathGeom.isRoughly(constraint.Value, value.Value):
                    PathLog.track(name, constraint.Type, 'update', i)
                    constr = Sketcher.Constraint(constraint.Type, constraint.First, value)
                    sketch.delConstraint(i)
                    sketch.recompute()
                    n = sketch.addConstraint(constr)
                    sketch.renameConstraint(n, constraint.Name)
                else:
                    PathLog.track(name, constraint.Type, 'unchanged')
            else:
                print(constraint.Name, constraint.Type)
            break

PropertyGroupBit = 'Bit'

class ToolBit(object):

    def __init__(self, obj, templateFile):
        PathLog.track(obj.Label, templateFile)
        self.obj = obj
        obj.addProperty('App::PropertyFile',       'BitTemplate', 'Base', translate('PathToolBit', 'Template for bit shape'))
        obj.addProperty('App::PropertyLink',       'BitBody',     'Base', translate('PathToolBit', 'The parametrized body representing the tool bit'))
        if templateFile is not None:
            obj.BitTemplate = templateFile
            self._setupBitFromTemplate(obj)
        self.onDocumentRestored(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        for obj in FreeCAD.ActiveDocument.Objects:
            if hasattr(obj, 'Proxy') and obj.Proxy == self:
                self.obj = obj
                break
        return None

    def bitPropertyNames(self, obj):
        return [prop for prop in obj.PropertiesList if obj.getGroupOfProperty(prop) == PropertyGroupBit]

    def onDocumentRestored(self, obj):
        obj.setEditorMode('BitTemplate', 1)
        obj.setEditorMode('BitBody', 2)
        obj.setEditorMode('Shape', 2)

        for prop in self.bitPropertyNames(obj):
            obj.setEditorMode(prop, 1)

    def onChanged(self, obj, prop):
        PathLog.track(obj.Label, prop)
        if prop == 'BitTemplate' and not 'Restore' in obj.State:
            self._setupBitFromTemplate(obj)
        #elif obj.getGroupOfProperty(prop) == PropertyGroupBit:
        #    self._updateBitShape(obj, [prop])

    def _updateBitShape(self, obj, properties=None):
        if not properties:
            properties = self.bitPropertyNames(obj)
        for prop in properties:
            for sketch in [o for o in obj.BitBody.Group if o.TypeId == 'Sketcher::SketchObject']:
                PathLog.track(obj.Label, sketch.Label, prop)
                updateConstraint(sketch, prop, obj.getPropertyByName(prop))
        self._copyBitShape(obj)

    def _copyBitShape(self, obj):
        obj.Document.recompute()
        if obj.BitBody and obj.BitBody.Shape:
            obj.Shape = obj.BitBody.Shape
        else:
            obj.Shape = Part.Shape()

    def _loadBitBody(self, obj, path=None):
        if not path:
            path = obj.BitTemplate
        docOpened = False
        doc = None
        for d in FreeCAD.listDocuments():
            if FreeCAD.getDocument(d).FileName == path:
                doc = FreeCAD.getDocument(d)
                break
        if doc is None:
            doc = FreeCAD.open(path)
            docOpened = True
        return (doc, docOpened)

    def _removeBitBody(self, obj):
        if obj.BitBody:
            obj.BitBody.removeObjectsFromDocument()
            obj.Document.removeObject(obj.BitBody.Name)
            obj.BitBody = None

    def _deleteBitSetup(self, obj):
        PathLog.track(obj.Label)
        self._removeBitBody(obj)
        self._copyBitShape(obj)
        for prop in self.bitPropertyNames(obj):
            obj.removeProperty(prop)

    def _setupBitFromTemplate(self, obj, path=None):
        (doc, docOpened) = self._loadBitBody(obj, path)

        obj.Label = doc.RootObjects[0].Label
        self._deleteBitSetup(obj)
        obj.BitBody = obj.Document.copyObject(doc.RootObjects[0], True)
        if docOpened:
            FreeCAD.closeDocument(doc.Name)

        if obj.BitBody.ViewObject:
            obj.BitBody.ViewObject.Visibility = False
        self._copyBitShape(obj)

        for sketch in [o for o in obj.BitBody.Group if o.TypeId == 'Sketcher::SketchObject']:
            for constraint in [c for c in sketch.Constraints if c.Name != '']:
                typ = ParameterTypeConstraint.get(constraint.Type)
                PathLog.track(constraint, typ)
                if typ is not None:
                    parts = [p.strip() for p in constraint.Name.split(';')]
                    prop = parts[0]
                    desc = ''
                    if len(parts) > 1:
                        desc  = parts[1]
                    obj.addProperty(typ, prop, PropertyGroupBit, desc)
                    obj.setEditorMode(prop, 1)
                    value = constraint.Value
                    if constraint.Type == 'Angle':
                        value = value * 180 / math.pi
                    PathUtil.setProperty(obj, prop, constraint.Value)

    def getBitThumbnail(self, obj):
        if obj.BitTemplate:
            with open(obj.BitTemplate, 'rb') as fd:
                zf = zipfile.ZipFile(fd)
                pf = zf.open('thumbnails/Thumbnail.png', 'r')
                data = pf.read()
                pf.close()
                return data
        else:
            return None


def Create(name = 'ToolBit', templateFile=None):
    obj = FreeCAD.ActiveDocument.addObject('Part::FeaturePython', name)
    obj.Proxy = ToolBit(obj, templateFile)
    return obj
