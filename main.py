#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2010-2011 Dan Moore
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import re
import math
import logging
import os
import urllib

from google.appengine.ext import webapp
from google.appengine.api import images
from google.appengine.api import memcache

from google.appengine.ext.webapp import util


from google.appengine.dist import use_library
use_library('django', '1.2')
from google.appengine.ext.webapp import template

from google.appengine.api.urlfetch import fetch


# load up our 1x1 PNG file for compositing when no label is defined or can be loaded
empty_png_file = open('1x1.png', 'rb')
empty_png = empty_png_file.read()
empty_png_file.close()

empty_png_def = (empty_png, 0, 0, 0.0, images.CENTER_CENTER)

class MainHandler(webapp.RequestHandler):
  
  def get(self):
    
    # special pre-defined sizes to use in lieu of number dimensions.  taken from dummyimage.com.
    sizes = {
        # Ad Sizes
        'mediumrectangle':      '300×250',
        'squarepopup':          '250×250',
        'verticalrectangle':	'240×400',
        'largerectangle':		'336×280',
        'rectangle':    		'180×150',
        'popunder':     		'720×300',
        'fullbanner':   		'468×60',
        'halfbanner':   		'234×60',
        'microbar':     		'88×31',
        'button1':      		'120×90',
        'button2':      		'120×60',
        'verticalbanner':		'120×240',
        'squarebutton': 		'125×125',
        'leaderboard':  		'728×90',
        'wideskyscraper':		'60×600',
        'skyscraper':   		'120×600',
        'halfpage': 	    	'300×600',
        
        # Screen Resolutions
        'cga':  	'320x200',
        'qvga':	    '320x240',
        'vga':	    '640x480',
        'wvga':	    '800x480',
        'svga':	    '800x480',
        'wsvga':	'1024x600',
        'xga':   	'1024x768',
        'wxga':	    '1280x800',
        'wsxga': 	'1440x900',
        'wuxga': 	'1920x1200',
        'wqxga':	'2560x1600',
        
        # Video Resolutions
        'ntsc': 	'720x480',
        'pal':  	'768x576',
        'hd720':	'1280x720',
        'hd1080':	'1920x1080',
    }

    size = None
    path = re.match(r"/(?P<size>[a-zA-Z0-9x]+)(\.(?P<ext>jpg|jpeg|png))?(,(?P<bgcolor>[0-9a-fA-F]{6}|[0-9a-fA-F]{3}|[0-9a-fA-F]{2}|[0-9a-fA-F]{1}))?$", self.request.path_info)
    
    if path:
        path_size = self.request.get('d', path.group('size'))
        
        if path_size in sizes:
            path_size = sizes[path_size]
        
        size = re.match(r"(?P<width>\d+)(x(?P<height>\d+))?", path_size)
    
    
    if size:
        ## determine extension/file type
        ext = self.request.get('t', path.group('ext') or 'png')
        
        if ext == 'png':
            mimetype = 'image/png'
            encoding = images.PNG
        else:
            mimetype = 'image/jpeg'
            encoding = images.JPEG
        
        
        ## determine colors
        bgcolor = self.request.get('b', path.group('bgcolor') or 'aaaaaa')
        fgcolor = self.request.get('f', '000000')
        
        # handle shortcut colors
        if len(bgcolor) == 1:
            bgcolor = bgcolor[0] + bgcolor[0] + bgcolor[0] + bgcolor[0] + bgcolor[0] + bgcolor[0]
        elif len(bgcolor) == 2:
            bgcolor = bgcolor[0] + bgcolor[1] + bgcolor[0] + bgcolor[1] + bgcolor[0] + bgcolor[1]
        elif len(bgcolor) == 3:
            bgcolor = bgcolor[0] + bgcolor[0] + bgcolor[1] + bgcolor[1] + bgcolor[2] + bgcolor[2]
            
        bgmatch = re.match(r"^[0-9a-fA-F]{6}$", bgcolor)
        if not bgmatch:
            bgcolor = 'aaaaaa'
            
        
        if len(fgcolor) == 1:
            fgcolor = fgcolor[0] + fgcolor[0] + fgcolor[0] + fgcolor[0] + fgcolor[0] + fgcolor[0]
        elif len(fgcolor) == 2:
            fgcolor = fgcolor[0] + fgcolor[1] + fgcolor[0] + fgcolor[1] + fgcolor[0] + fgcolor[1]
        elif len(fgcolor) == 3:
            fgcolor = fgcolor[0] + fgcolor[0] + fgcolor[1] + fgcolor[1] + fgcolor[2] + fgcolor[2]
        
        fgmatch = re.match(r"^[0-9a-fA-F]{6}$", fgcolor)
        if not fgmatch:
            fgcolor = 'aaaaaa'
        
        ## determine size
        width = int(size.group('width'))
        
        # if only one dimension defined, image is square
        try:
            height = int(size.group('height'))
        except TypeError:
            height = width
        
        
        ## dimensions
        dimensions = str(width) + 'x' + str(height)
        
        
        ## label is what will be shown
        default_label = str(width) + u'×' + str(height)
        if path.group('size') in sizes:
            default_label = path.group('size') + '|(' + default_label + ')'
        
        label = self.request.get('l', default_label)
        
        
        ## determine size of the font used for title needs to vary depending on width
        title_font_size = (float(width)/max(len(label),1)) * (1.4 if width > 16 else 1.9)
        title_font_size = min(title_font_size, 100)
        
        # make sure it is reasonably sized based on height too
        title_font_size = min(title_font_size, height*0.6)
        
        # allow font size to be overridden
        try:
            title_font_size = int(self.request.get('s'))
        except ValueError:
            pass
        
        if width <= 4000 and height <= 4000:
            # the label images must be 1000 pixels or less in each dimension
            label_height = min(height, 1000, int(title_font_size + 8) * (1 + label.count('|')) + 10*label.count('|'))
            label_width  = min(width, 1000, int(300000/label_height)) # must also be less than 300000 total pixels
            url = 'http://chart.apis.google.com/chart?chs=' + str(label_width) + 'x' + str(label_height) + '&cht=p3&chtt=' + urllib.quote_plus(label.encode('utf-8')) + '&chts=' + fgcolor + ',' + str(title_font_size) + '&chf=bg,s,' + bgcolor
            
            
            # see if we've already generated this image and have it cached in memcache
            cache_key = os.environ['CURRENT_VERSION_ID'] + "|" + url + "|" + str(width) + "|" + str(height) + "|" + str(bgcolor) + "|" + str(encoding)
            full_img = memcache.get(cache_key)
            
            if full_img is None:
                # not found in memcache, so try creating it

                try:
                    label_img = fetch(url=url, deadline=10)
                
                    full_img = images.composite([(label_img.content, 0, 0, 1.0, images.CENTER_CENTER)], width, height, int('ff'+bgcolor,16), encoding)
                    memcache.add(cache_key, full_img)
                    
                except images.BadImageError:
                    # self.response.set_status(400)
                    # self.response.out.write("Error from Google Chart: '" + label_img.content + "'.")
                    logging.error("Error from Google Chart: '" + label_img.content + "'.")
                    full_img = images.composite([empty_png_def], width, height, int('ff'+bgcolor,16), encoding)
                    
                    # since this is the result of an error, we're returning an image without intended label now but we want client to try again next time
                    self.response.headers['Cache-Control'] = 'no-cache'

                except Exception, ex:
                    logging.warning(ex)
                    full_img = images.composite([empty_png_def], width, height, int('ff'+bgcolor,16), encoding)
                    
                    # since this is the result of an error, we're returning an image without intended label now but we want client to try again next time
                    self.response.headers['Cache-Control'] = 'no-cache'
                
            self.response.headers['Content-Type'] = mimetype
            self.response.out.write(full_img)

        
        ## image requested is too damn big
        else:
            self.response.set_status(400)
            self.response.out.write("Dimensions requested (" + dimensions + ") are bigger than supported.")
    
    
    ## URL request isn't recognized
    else:
        self.response.set_status(400)
        writeError(self.response)



def writeError(response):
    path = os.path.join(os.path.dirname(__file__), 'error.html')
    response.out.write(template.render(path, {}))


def main():
    application = webapp.WSGIApplication([('.*', MainHandler)],
                                       debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
