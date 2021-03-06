#!/usr/bin/env python

# """
# Name: 'YASim (.xml)'
# OpenSCAD: 2020
# Group: 'Import'
# Tooltip: 'Converts YASim FDM geometry to OpenSCAD file'
# """

__author__ = "ThunderFly s.r.o. < info # thunderfly : cz >"
__url__ = ["http://www.flightgear.org/", "http://cvs.flightgear.org/viewvc/source/utils/Modeller/yasim_import.py"]
__version__ = "0.1"
__bpydoc__ = """\
yasim2scad.py loads YASim FDM geometry XML file and make OpenSCAD file
======================================================================

This is good enough for simple checks. But if you are working on the YASim configuration, then you need a
quick and convenient way to reload the file.


If the 3D model is displaced with respect to the FDM model, then the <offsets> values from the
model animation XML file should be added as comment to the YASim config file, as a line all by
itself, with no spaces surrounding the equal signs. Spaces elsewhere are allowed. For example:

  <offsets>
      <x-m>3.45</x-m>
      <z-m>-0.4</z-m>
      <pitch-deg>5</pitch-deg>
  </offsets>

becomes:

  <!-- offsets: x=3.45 z=-0.4 p=5 -->

Possible variables are:

  x ... <x-m>
  y ... <y-m>
  z ... <z-m>
  h ... <heading-deg>
  p ... <pitch-deg>
  r ... <roll-deg>

Of course, absolute FDM coordinates can then no longer directly be read from 3D view.
The cursor coordinates display in the script area, however, shows the coordinates in YASim space.
Note that object names don't contain XML indices but element numbers. YASim_flap0#2 is the third
flap0 in the whole file, not necessarily in its parent XML group. A floating point part in the
object name (e.g. YASim_flap0#2.004) only means that the geometry has been reloaded that often.
It's an unavoidable consequence of how Blender deals with meshes.


Elements are displayed as follows:

  cockpit                             -> monkey head
  fuselage                            -> blue "tube" (with only 12 sides for less clutter); center at "a"
  vstab                               -> red with yellow control surfaces (flap0, flap1, slat, spoiler)
  wing/mstab/hstab                    -> green with yellow control surfaces (which are always 20 cm deep);
                                         symmetric surfaces are only displayed on the left side, unless
                                         the "Mirror" button is active
  thrusters (jet/propeller/thruster)  -> dashed line from center to actionpt;
                                         arrow from actionpt along thrust vector (always 1 m long);
                                         propeller circle
  rotor                               -> radius and rel_len_blade_start circle, normal and forward vector,
                                         one blade at phi0 with direction arrow near blade tip
  gear                                -> contact point and compression vector (no arrow head)
  tank                                -> magenta cube (10 cm side length)
  weight                              -> inverted cyan cone
  ballast                             -> yellow cylinder
  hitch                               -> hexagon (10 cm diameter)
  hook                                -> dashed line for up angle, T-line for down angle
  launchbar                           -> dashed line for up angles, T-line for down angles
                                         (launchbar and holdback each)


The Mirror button complements symmetrical surfaces (wing/hstab/mstab) and control surfaces
(flap0/flap1/slat/spoiler). This is useful for asymmetrical aircraft, but has the disadvantage
that it moves the surfaces' object centers from their usual place, yasim's [x, y, z] value,
to [0, 0, 0]. Turning mirroring off restores the object center.



Environment variable BLENDER_YASIM_IMPORT can be set to a space-separated list of options:

  $ BLENDER_YASIM_IMPORT="mirror verbose"  blender

whereby:

  verbose  ... enables verbose logs
  mirror   ... enables mirroring of symmetric surfaces
"""


#--------------------------------------------------------------------------------
# Copyright (C) 2009  Melchior FRANZ  < mfranz # aon : at >
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#--------------------------------------------------------------------------------

import sys
import math
import string
import numpy as np
from pyopenscad import *
from xml.sax import handler, make_parser

YASIM_MATRIX = np.matrix([[-1, 0, 0, 0], [0, -1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
ORIGIN = np.array([0, 0, 0])
X = np.array([1, 0, 0])
Y = np.array([0, 1, 0])
Z = np.array([0, 0, 1])

DEG2RAD = math.pi / 180
RAD2DEG = 180 / math.pi

#NO_EVENT = 0
#RELOAD_BUTTON = 1
#CURSOR_BUTTON = 2
#MIRROR_BUTTON = 3



class Global:
    path = ""
    matrix = None
    data = None

class Abort(Exception):
    def __init__(self, msg, term = None):
        self.msg = msg
        self.term = term



def log(msg):
    print(msg)



def draw_dashed_line(mesh, start, end):
    w = 0.04
    step = w * (end - start).normalize()
    n = len(mesh.verts)
    for i in range(int(1 + 0.5 * (end - start).length / w)):
        a = start + 2 * i * step
        b = a + step
        if (b - end).length < step.length:
            b = end
        mesh.verts.extend([a, b])
        mesh.edges.extend([n + 2 * i, n + 2 * i + 1])



def draw_arrow(mesh, start, end):
    v = end - start
    m = v.toTrackQuat('x', 'z').toMatrix().resize4x4() * TranslationMatrix(start)
    v = v.length * X
    n = len(mesh.verts)
    mesh.verts.extend([ORIGIN * m , v * m, (v - 0.05 * X + 0.05 * Y) * m, (v - 0.05 * X - 0.05 * Y) * m]) # head
    mesh.verts.extend([(ORIGIN + 0.05 * Y) * m, (ORIGIN - 0.05 * Y) * m]) # base
    mesh.edges.extend([[n, n + 1], [n + 1, n + 2], [n + 1, n + 3], [n + 4, n + 5]])



def draw_circle(mesh, numpoints, radius, matrix):
    n = len(mesh.verts)
    for i in range(numpoints):
        angle = 2.0 * math.pi * i / numpoints
        v = np.array([radius * math.cos(angle), radius * math.sin(angle), 0])
        mesh.verts.extend([v * matrix])
    for i in range(numpoints):
        i1 = (i + 1) % numpoints
        mesh.edges.extend([[n + i, n + i1]])



class Item:
    scene = union()

    def make_twosided(self, mesh):
        pass
        #mesh.faceUV = True
        #for f in mesh.faces:
        #    f.mode |= Blender.Mesh.FaceModes.TWOSIDE | Blender.Mesh.FaceModes.OBCOL

class Cockpit(Item):
    def __init__(self, center):
        '''    mesh = Blender.Mesh.Primitives.Monkey()
        mesh.transform(ScaleMatrix(0.13, 4) * Euler(90, 0, 90).toMatrix().resize4x4() * TranslationMatrix(np.array([-0.1, 0, -0.032)))
        obj = self.scene.objects.new(mesh, "YASim_cockpit")
        obj.setMatrix(TranslationMatrix(center) * Global.matrix)
        '''

    def set_color(self, obj, color):
        return

        '''
        mat = Blender.Material.New()
        mat.setRGBCol(color[0], color[1], color[2])
        mat.setAlpha(color[3])
        mat.mode |= Blender.Material.Modes.ZTRANSP | Blender.Material.Modes.TRANSPSHADOW
        obj.transp = True

        mesh = obj.getData(mesh = True)
        mesh.materials += [mat]

        for f in mesh.faces:
            f.smooth = True
        mesh.calcNormals()
        '''


class Tank(Item):
    def __init__(self, name, center):
        mesh = translate(v = [center[0]*1000, center[1]*1000, center[2]*1000])(     ## convert YASim meters to OpenSCAD milimeters
        color([0.3, 0.3, 0.9, 0.5])(cube(size=20, center = True )),
        sphere(15))
        #mesh.translate()(mesh)
        mesh.set_modifier('background')
        Item.scene.add(mesh)

class Ballast(Item):
    def __init__(self, name, center, mass):
        mesh = translate(v = [center[0]*1000, center[1]*1000, center[2]*1000])(
        color([0.3, 0.5, 0.9, 0.5])(cylinder(h=mass*50, r=20, center = True )))     ## multiply mass by arbitrary value to visualise it.
        #mesh.translate()(mesh)
        mesh.set_modifier('background')
        Item.scene.add(mesh)

class Weight(Item):
    def __init__(self, name, center):
        mesh = translate(v = [center[0]*1000, center[1]*1000, center[2]*1000])(
        color([0.3, 0.4, 0.9, 0.5])(cylinder(h=50, r=20, center = True )))
        #mesh.translate()(mesh)
        mesh.set_modifier('background')
        Item.scene.add(mesh)

class Gear(Item):
    def __init__(self, name, center, compression):
        '''    mesh = Blender.Mesh.New()
        mesh.verts.extend([ORIGIN, compression])
        mesh.edges.extend([0, 1])
        obj = self.scene.objects.new(mesh, name)
        obj.setMatrix(TranslationMatrix(center) * Global.matrix)
        '''

class Hook(Item):
    def __init__(self, name, center, length, up_angle, dn_angle):
        '''    mesh = Blender.Mesh.New()
        up = ORIGIN - length * math.cos(up_angle * DEG2RAD) * X - length * math.sin(up_angle * DEG2RAD) * Z
        dn = ORIGIN - length * math.cos(dn_angle * DEG2RAD) * X - length * math.sin(dn_angle * DEG2RAD) * Z
        mesh.verts.extend([ORIGIN, dn, dn + 0.05 * Y, dn - 0.05 * Y])
        mesh.edges.extend([[0, 1], [2, 3]])
        draw_dashed_line(mesh, ORIGIN, up)
        draw_dashed_line(mesh, ORIGIN, dn)
        obj = self.scene.objects.new(mesh, name)
        obj.setMatrix(TranslationMatrix(center) * Global.matrix)
        '''


class Launchbar(Item):
    def __init__(self, name, lb, lb_length, hb, hb_length, up_angle, dn_angle):
        '''    mesh = Blender.Mesh.New()
        hb = hb - lb
        lb_tip = ORIGIN + lb_length * math.cos(dn_angle * DEG2RAD) * X - lb_length * math.sin(dn_angle * DEG2RAD) * Z
        hb_tip = hb - hb_length * math.cos(dn_angle * DEG2RAD) * X - hb_length * math.sin(dn_angle * DEG2RAD) * Z
        mesh.verts.extend([lb_tip, ORIGIN, hb, hb_tip, lb_tip + 0.05 * Y, lb_tip - 0.05 * Y, hb_tip + 0.05 * Y, hb_tip - 0.05 * Y])
        mesh.edges.extend([[0, 1], [1, 2], [2, 3], [4, 5], [6, 7]])
        draw_dashed_line(mesh, ORIGIN, lb_length * math.cos(up_angle * DEG2RAD) * X - lb_length * math.sin(up_angle * DEG2RAD) * Z)
        draw_dashed_line(mesh, hb, hb - hb_length * math.cos(up_angle * DEG2RAD) * X - hb_length * math.sin(up_angle * DEG2RAD) * Z)
        obj = self.scene.objects.new(mesh, name)
        obj.setMatrix(TranslationMatrix(lb) * Global.matrix)
        '''

class Hitch(Item):
    def __init__(self, name, center):
        '''        mesh = Blender.Mesh.Primitives.Circle(6, 0.1)
        obj = self.scene.objects.new(mesh, name)
        obj.setMatrix(RotationMatrix(90, 4, "x") * TranslationMatrix(center) * Global.matrix)

        '''

class Thrust:
    def set_actionpt(self, p):
        self.actionpt = p

    def set_dir(self, d):
        self.thrustvector = d



class Thruster(Thrust, Item):
    def __init__(self, name, center, thrustvector):
        (self.name, self.center, self.actionpt, self.thrustvector) = (name, center, center, thrustvector)

    def __del__(self):
        '''        a = self.actionpt - self.center
        mesh = Blender.Mesh.New()
        draw_dashed_line(mesh, ORIGIN, a)
        draw_arrow(mesh, a, a + self.thrustvector.normalize())
        obj = self.scene.objects.new(mesh, self.name)
        obj.setMatrix(TranslationMatrix(self.center) * Global.matrix)
        '''


class Propeller(Thrust, Item):
    def __init__(self, name, center, radius):
        (self.name, self.center, self.radius, self.actionpt, self.thrustvector) = (name, center, radius, center, -X)
    #    print(radius)

    def __del__(self):
        mesh = translate(v = [self.center[0]*1000, self.center[1]*1000, self.center[2]*1000])(
        rotate([0,90,0])(
        color([0.5, 0.4, 0.9, 0.5])
        (cylinder(h=2, r=self.radius*1000, center = True )))
        )
        mesh.set_modifier('background')
        Item.scene.add(mesh)

        '''        a = self.actionpt - self.center
        matrix = self.thrustvector.toTrackQuat('z', 'x').toMatrix().resize4x4() * TranslationMatrix(a)

        mesh = Blender.Mesh.New()
        mesh.verts.extend([ORIGIN * matrix, (ORIGIN + self.radius * X) * matrix])
        mesh.edges.extend([[0, 1]])
        draw_dashed_line(mesh, ORIGIN, a)
        draw_arrow(mesh, a, a + self.thrustvector.normalize())

        draw_circle(mesh, 128, self.radius, matrix)
        obj = self.scene.objects.new(mesh, self.name)
        obj.setMatrix(TranslationMatrix(self.center) * Global.matrix)
        '''


class Jet(Thrust, Item):
    def __init__(self, name, center, rotate):
        (self.name, self.center, self.actionpt) = (name, center, center)
        self.thrustvector = -X * RotationMatrix(rotate, 4, "y")

    def __del__(self):
        '''        a = self.actionpt - self.center
        mesh = Blender.Mesh.New()
        draw_dashed_line(mesh, ORIGIN, a)
        draw_arrow(mesh, a, a + self.thrustvector.normalize())
        obj = self.scene.objects.new(mesh, self.name)
        obj.setMatrix(TranslationMatrix(self.center) * Global.matrix)
        '''


class Fuselage(Item):
    def __init__(self, name, a, b, width, taper, midpoint):
        '''        numvert = 12
        angle = []
        for i in range(numvert):
            alpha = i * 2 * math.pi / float(numvert)
            angle.append([math.cos(alpha), math.sin(alpha)])

        axis = b - a
        length = axis.length
        mesh = Blender.Mesh.New()

        for i in range(numvert):
            mesh.verts.extend([[0, 0.5 * width * taper * angle[i][0], 0.5 * width * taper * angle[i][1]]])
        for i in range(numvert):
            mesh.verts.extend([[midpoint * length, 0.5 * width * angle[i][0], 0.5 * width * angle[i][1]]])
        for i in range(numvert):
            mesh.verts.extend([[length, 0.5 * width * taper * angle[i][0], 0.5 * width * taper * angle[i][1]]])
        for i in range(numvert):
            i1 = (i + 1) % numvert
            mesh.faces.extend([[i, i1, i1 + numvert, i + numvert]])
            mesh.faces.extend([[i + numvert, i1 + numvert, i1 + 2 * numvert, i + 2 * numvert]])

        mesh.verts.extend([ORIGIN, length * X])
        obj = self.scene.objects.new(mesh, name)
        obj.setMatrix(axis.toTrackQuat('x', 'y').toMatrix().resize4x4() * TranslationMatrix(a) * Global.matrix)
        self.set_color(obj, [0, 0, 0.5, 0.4])
        '''


class Rotor(Item):
    def __init__(self, name, center, up, fwd, numblades, radius, chord, twist, taper, rel_len_blade_start, phi0, ccw):
        mesh = translate(v = [center[0]*1000, center[1]*1000, center[2]*1000])(
        color([0.6, 0.4, 0.9, 0.5])
        (cylinder(h=2, r=radius*1000, center = True )))
        mesh.set_modifier('background')
        Item.scene.add(mesh)

        '''        matrix = RotationMatrix(phi0, 4, "z") * up.toTrackQuat('z', 'x').toMatrix().resize4x4()
        invert = matrix.copy().invert()
        direction = [-1, 1][ccw]
        twist *= DEG2RAD
        a = ORIGIN + rel_len_blade_start * radius * X
        b = ORIGIN + radius * X
        tw = 0.5 * chord * taper * math.cos(twist) * Y + 0.5 * direction * chord * taper * math.sin(twist) * Z

        mesh = Blender.Mesh.New()
        mesh.verts.extend([ORIGIN, a, b, a + 0.5 * chord * Y, a - 0.5 * chord * Y, b + tw, b - tw])
        mesh.edges.extend([[0, 1], [1, 2], [1, 3], [1, 4], [3, 5], [4, 6], [5, 6]])
        draw_circle(mesh, 64, rel_len_blade_start * radius, Matrix())
        draw_circle(mesh, 128, radius, Matrix())
        draw_arrow(mesh, ORIGIN, up * invert)
        draw_arrow(mesh, ORIGIN, fwd * invert)
        b += 0.1 * X + direction * chord * Y
        draw_arrow(mesh, b, b + min(0.5 * radius, 1) * direction * Y)
        obj = self.scene.objects.new(mesh, name)
        obj.setMatrix(matrix * TranslationMatrix(center) * Global.matrix)
        '''


class Wing(Item):
    def __init__(self, name, root, length, chord, incidence, twist, taper, sweep, dihedral):
        '''        #  <1--0--2
        #   \  |  /
        #    4-3-5
        self.is_symmetric = not name.startswith("YASim_vstab#")
        mesh = Blender.Mesh.New()
        mesh.verts.extend([ORIGIN, ORIGIN + 0.5 * chord * X, ORIGIN - 0.5 * chord * X])
        tip = ORIGIN + math.cos(sweep * DEG2RAD) * length * Y - math.sin(sweep * DEG2RAD) * length * X
        tipfore = tip + 0.5 * taper * chord * math.cos(twist * DEG2RAD) * X + 0.5 * taper * chord * math.sin(twist * DEG2RAD) * Z
        tipaft = tip + tip - tipfore
        mesh.verts.extend([tip, tipfore, tipaft])
        mesh.faces.extend([[0, 1, 4, 3], [2, 0, 3, 5]])

        self.make_twosided(mesh)

        obj = self.scene.objects.new(mesh, name)
        mesh.transform(Euler(dihedral, -incidence, 0).toMatrix().resize4x4())
        self.set_color(obj, [[0.5, 0.0, 0, 0.5], [0.0, 0.5, 0, 0.5]][self.is_symmetric])
        (self.obj, self.mesh) = (obj, mesh)

        if self.is_symmetric and Global.mirror_button.val:
            mod = obj.modifiers.append(Blender.Modifier.Type.MIRROR)
            mod[Blender.Modifier.Settings.AXIS_X] = False
            mod[Blender.Modifier.Settings.AXIS_Y] = True
            mod[Blender.Modifier.Settings.AXIS_Z] = False
            mesh.transform(TranslationMatrix(root)) # must move object center to x axis
            obj.setMatrix(Global.matrix)
        else:
            obj.setMatrix(TranslationMatrix(root) * Global.matrix)'''

    def add_flap(self, name, start, end):
        '''    a = np.array([self.mesh.verts[2].co)
        b = np.array([self.mesh.verts[5].co)
        c = 0.2 * (np.array([self.mesh.verts[0].co - a)).normalize()
        m = self.obj.getMatrix()

        mesh = Blender.Mesh.New()
        i0 = a + start * (b - a)
        i1 = a + end * (b - a)
        mesh.verts.extend([i0, i1, i0 + c, i1 + c])
        mesh.faces.extend([[0, 1, 3, 2]])

        self.make_twosided(mesh)

        obj = self.scene.objects.new(mesh, name)
        obj.setMatrix(m)
        self.set_color(obj, [0.8, 0.8, 0, 0.9])

        if self.is_symmetric and Global.mirror_button.val:
            mod = obj.modifiers.append(Blender.Modifier.Type.MIRROR)
            mod[Blender.Modifier.Settings.AXIS_X] = False
            mod[Blender.Modifier.Settings.AXIS_Y] = True
            mod[Blender.Modifier.Settings.AXIS_Z] = False
'''


class import_yasim(handler.ErrorHandler, handler.ContentHandler):
    ignored = ["cruise", "approach", "control-input", "control-output", "control-speed", \
            "control-setting", "stall", "airplane", "piston-engine", "turbine-engine", \
            "rotorgear", "tow", "winch", "solve-weight"]


    # err_handler
    def warning(self, exception):
        print((self.error_string("Warning", exception)))

    def error(self, exception):
        print((self.error_string("Error", exception)))

    def fatalError(self, exception):
        raise Abort(str(exception), self.error_string("Fatal", exception))

    def error_string(self, tag, e):
        (column, line) = (e.getColumnNumber(), e.getLineNumber())
        return "%s: %s\n%s%s^"  % (tag, str(e), Global.data[line - 1], column * ' ')

    # doc_handler
    def setDocumentLocator(self, locator):
        self.locator = locator

    def startDocument(self):
        self.tags = []
        self.counter = {}
        self.items = [None]

    def endDocument(self):
        print(scad_render(Item.scene))
        scad_render_to_file(Item.scene, Global.pathout)

    def startElement(self, tag, attrs):
        if len(self.tags) == 0 and tag != "airplane":
            raise Abort("this isn't a YASim config file (bad root tag at line %d)" % self.locator.getLineNumber())

        self.tags.append(tag)
        path = string.join(self.tags, '/')
        item = Item()
        parent = self.items[-1]

        if self.counter.has_key(tag):
            self.counter[tag] += 1
        else:
            self.counter[tag] = 0

        if tag == "cockpit":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            log("\033[31mcockpit x=%f y=%f z=%f\033[m" % (c[0], c[1], c[2]))
            item = Cockpit(c)

        elif tag == "fuselage":
            a = np.array([float(attrs["ax"]), float(attrs["ay"]), float(attrs["az"])])
            b = np.array([float(attrs["bx"]), float(attrs["by"]), float(attrs["bz"])])
            width = float(attrs["width"])
            taper = float(attrs.get("taper", 1))
            midpoint = float(attrs.get("midpoint", 0.5))
            log("\033[32mfuselage ax=%f ay=%f az=%f bx=%f by=%f bz=%f width=%f taper=%f midpoint=%f\033[m" % \
                    (a[0], a[1], a[2], b[0], b[1], b[2], width, taper, midpoint))
            item = Fuselage("YASim_%s#%d" % (tag, self.counter[tag]), a, b, width, taper, midpoint)

        elif tag == "gear":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            compression = float(attrs.get("compression", 1))
            up = Z * compression
            if attrs.has_key("upx"):
                up = np.linalg.norm(np.array([float(attrs["upx"]), float(attrs["upy"]), float(attrs["upz"])])) * compression
            log("\033[35;1mgear x=%f y=%f z=%f compression=%f upx=%f upy=%f upz=%f\033[m" \
                    % (c[0], c[1], c[2], compression, up[0], up[1], up[2]))
            item = Gear("YASim_gear#%d" % self.counter[tag], c, up)

        elif tag == "jet":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            rotate = float(attrs.get("rotate", 0))
            log("\033[36;1mjet x=%f y=%f z=%f rotate=%f\033[m" % (c[0], c[1], c[2], rotate))
            item = Jet("YASim_jet#%d" % self.counter[tag], c, rotate)

        elif tag == "propeller":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            radius = float(attrs["radius"])
            log("\033[36;1m%s x=%f y=%f z=%f radius=%f\033[m" % (tag, c[0], c[1], c[2], radius))
            item = Propeller("YASim_propeller#%d" % self.counter[tag], c, radius)

        elif tag == "thruster":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            v = np.array([float(attrs["vx"]), float(attrs["vy"]), float(attrs["vz"])])
            log("\033[36;1m%s x=%f y=%f z=%f vx=%f vy=%f vz=%f\033[m" % (tag, c[0], c[1], c[2], v[0], v[1], v[2]))
            item = Thruster("YASim_thruster#%d" % self.counter[tag], c, v)

        elif tag == "actionpt":
            if not isinstance(parent, Thrust):
                raise Abort("%s is not part of a thruster/propeller/jet at line %d" \
                        % (path, self.locator.getLineNumber()))

            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            log("\t\033[36mactionpt x=%f y=%f z=%f\033[m" % (c[0], c[1], c[2]))
            parent.set_actionpt(c)

        elif tag == "dir":
            if not isinstance(parent, Thrust):
                raise Abort("%s is not part of a thruster/propeller/jet at line %d" \
                        % (path, self.locator.getLineNumber()))

            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            log("\t\033[36mdir x=%f y=%f z=%f\033[m" % (c[0], c[1], c[2]))
            parent.set_dir(c)

        elif tag == "tank":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            log("\033[34;1m%s x=%f y=%f z=%f\033[m" % (tag, c[0], c[1], c[2]))
            item = Tank("YASim_tank#%d" % self.counter[tag], c)

        elif tag == "ballast":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            mass = float(attrs.get("mass-kg", 1))
            log("\033[34m%s x=%f y=%f z=%f mass=%f\033[m" % (tag, c[0], c[1], c[2], mass))
            item = Ballast("YASim_ballast#%d" % self.counter[tag], c, mass)

        elif tag == "weight":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            log("\033[34m%s x=%f y=%f z=%f\033[m" % (tag, c[0], c[1], c[2]))
            item = Weight("YASim_weight#%d" % self.counter[tag], c)

        elif tag == "hook":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            length = float(attrs.get("length", 1))
            up_angle = float(attrs.get("up-angle", 0))
            down_angle = float(attrs.get("down-angle", 70))
            log("\033[35m%s x=%f y=%f z=%f length=%f up-angle=%f down-angle=%f\033[m" \
                    % (tag, c[0], c[1], c[2], length, up_angle, down_angle))
            item = Hook("YASim_hook#%d" % self.counter[tag], c, length, up_angle, down_angle)

        elif tag == "hitch":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            log("\033[35m%s x=%f y=%f z=%f\033[m" % (tag, c[0], c[1], c[2]))
            item = Hitch("YASim_hitch#%d" % self.counter[tag], c)

        elif tag == "launchbar":
            c = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            length = float(attrs.get("length", 1))
            up_angle = float(attrs.get("up-angle", -45))
            down_angle = float(attrs.get("down-angle", 45))
            holdback = np.array([float(attrs.get("holdback-x", c[0])), float(attrs.get("holdback-y", c[1])), float(attrs.get("holdback-z", c[2]))])
            holdback_length = float(attrs.get("holdback-length", 2))
            log("\033[35m%s x=%f y=%f z=%f length=%f down-angle=%f up-angle=%f holdback-x=%f holdback-y=%f holdback-z+%f holdback-length=%f\033[m" \
                    % (tag, c[0], c[1], c[2], length, down_angle, up_angle, \
                    holdback[0], holdback[1], holdback[2], holdback_length))
            item = Launchbar("YASim_launchbar#%d" % self.counter[tag], c, length, holdback, holdback_length, up_angle, down_angle)

        elif tag == "wing" or tag == "hstab" or tag == "vstab" or tag == "mstab":
            root = np.array([float(attrs["x"]), float(attrs["y"]), float(attrs["z"])])
            length = float(attrs["length"])
            chord = float(attrs["chord"])
            incidence = float(attrs.get("incidence", 0))
            twist = float(attrs.get("twist", 0))
            taper = float(attrs.get("taper", 1))
            sweep = float(attrs.get("sweep", 0))
            dihedral = float(attrs.get("dihedral", [0, 90][tag == "vstab"]))
            log("\033[33;1m%s x=%f y=%f z=%f length=%f chord=%f incidence=%f twist=%f taper=%f sweep=%f dihedral=%f\033[m" \
                    % (tag, root[0], root[1], root[2], length, chord, incidence, twist, taper, sweep, dihedral))
            item = Wing("YASim_%s#%d" % (tag, self.counter[tag]), root, length, chord, incidence, twist, taper, sweep, dihedral)

        elif tag == "flap0" or tag == "flap1" or tag == "slat" or tag == "spoiler":
            if not isinstance(parent, Wing):
                raise Abort("%s is not part of a wing or stab at line %d" \
                        % (path, self.locator.getLineNumber()))

            start = float(attrs["start"])
            end = float(attrs["end"])
            log("\t\033[33m%s start=%f end=%f\033[m" % (tag, start, end))
            parent.add_flap("YASim_%s#%d" % (tag, self.counter[tag]), start, end)

        elif tag == "rotor":
            c = np.array([float(attrs.get("x", 0)), float(attrs.get("y", 0)), float(attrs.get("z", 0))])
            norm = np.array([float(attrs.get("nx", 0)), float(attrs.get("ny", 0)), float(attrs.get("nz", 1))])
            fwd = np.array([float(attrs.get("fx", 1)), float(attrs.get("fy", 0)), float(attrs.get("fz", 0))])
            diameter = float(attrs.get("diameter", 10.2))
            numblades = int(attrs.get("numblades", 4))
            chord = float(attrs.get("chord", 0.3))
            twist = float(attrs.get("twist", 0))
            taper = float(attrs.get("taper", 1))
            rel_len_blade_start = float(attrs.get("rel-len-blade-start", 0))
            phi0 = float(attrs.get("phi0", 0))
            ccw = not not int(attrs.get("ccw", 0))

            log(("\033[36;1mrotor x=%f y=%f z=%f nx=%f ny=%f nz=%f fx=%f fy=%f fz=%f numblades=%d diameter=%f " \
                    + "chord=%f twist=%f taper=%f rel_len_blade_start=%f phi0=%f ccw=%d\033[m") \
                    % (c[0], c[1], c[2], norm[0], norm[1], norm[2], fwd[0], fwd[1], fwd[2], numblades, \
                    diameter, chord, twist, taper, rel_len_blade_start, phi0, ccw))
            item = Rotor("YASim_rotor#%d" % self.counter[tag], c, norm, fwd, numblades, 0.5 * diameter, chord, \
                    twist, taper, rel_len_blade_start, phi0, ccw)

        elif tag not in self.ignored:
            log("\033[30;1m%s\033[m" % path)

        self.items.append(item)

    def endElement(self, tag):
        self.tags.pop()
        self.items.pop()


## extract possible offset matrix see above in destription
def extract_matrix(filedata, tag):
    v = { 'x': 0.0, 'y': 0.0, 'z': 0.0, 'h': 0.0, 'p': 0.0, 'r': 0.0 }
    has_offsets = False
    for line in filedata:
        line = string.strip(line)
        if not line.startswith("<!--") or not line.endswith("-->"):
            continue
        line = string.strip(line[4:-3])
        if not string.lower(line).startswith("%s:" % tag):
            continue
        line = string.strip(line[len(tag) + 1:])
        for assignment in string.split(line):
            (key, value) = string.split(assignment, '=', 2)
            v[string.strip(key)] = float(string.strip(value))
            has_offsets = True

    if not has_offsets:
        return None

    print(("using offsets: x=%f y=%f z=%f h=%f p=%f r=%f" % (v['x'], v['y'], v['z'], v['h'], v['p'], v['r'])))
    return Euler(v['r'], v['p'], v['h']).toMatrix().resize4x4() * TranslationMatrix(np.array([v['x'], v['y'], v['z']]))



def load_yasim_config(pathin, pathout):

    xml_handler = import_yasim()
    Global.yasim = make_parser()
    Global.yasim.setContentHandler(xml_handler)
    Global.yasim.setErrorHandler(xml_handler)

    print(("loading '%s'" % pathin))
    try:
        f = open(pathin)
        Global.data = f.readlines()
        f.close

        Global.path = pathin
        Global.pathout = pathout
        Global.matrix = YASIM_MATRIX
        matrix = extract_matrix(Global.data, "offsets")
        if matrix:
            Global.matrix *= matrix.invert()

        Global.yasim.parse(pathin)

    except Abort, e:
        print(("%s\nAborting ..." % (e.term or e.msg)))

def create_scad(filename):
    d = difference()(
        color([0.3, 0.3, 0.9, 0.5])(cube(size=[10,10,10], center = True )),
        sphere(7).set_modifier('background')
    )

    Global.test= 5

    #print(Global.data)

#    print (scad_render(d))
    scad_render_to_file(d, filename)

def main():
    if len(sys.argv) != 3:
        sys.stderr.write("Invalid number of arguments.\n")
        sys.stderr.write("Usage: %s YASimfile scadfile\n" % (sys.argv[0], ))
        sys.exit(1)

    load_yasim_config(sys.argv[1],sys.argv[2])

main()
