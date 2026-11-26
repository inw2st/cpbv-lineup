"""Map Windows OCR's deskewed word rectangles back into screenshot pixels."""
import copy
import math


def screenshot_coordinates(ocr,image_size):
    if ocr.get('coordinates_corrected'):return ocr
    result=copy.deepcopy(ocr)
    angle=float(result.get('text_angle') or 0)
    width=result.get('image_width') or image_size[0]*2
    height=result.get('image_height') or image_size[1]*2
    if angle:
        theta=math.radians(angle);co=math.cos(theta);si=math.sin(theta)
        cx,cy=width/2,height/2
        for line in result.get('lines',[]):
            for word in line.get('words',[]):
                x,y,w,h=(word[key] for key in ('x','y','width','height'))
                points=[]
                for px,py in ((x,y),(x+w,y),(x,y+h),(x+w,y+h)):
                    dx,dy=px-cx,py-cy
                    points.append((cx+co*dx-si*dy,cy+si*dx+co*dy))
                xs,ys=zip(*points)
                word.update(x=min(xs),y=min(ys),width=max(xs)-min(xs),height=max(ys)-min(ys))
    result['coordinates_corrected']=True
    result['coordinate_correction']={'angle':angle,'center':[width/2,height/2],
                                     'target':'original screenshot, OCR 2x units'}
    return result
