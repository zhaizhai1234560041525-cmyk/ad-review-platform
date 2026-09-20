"""Decode and verify user posters without altering image content."""
import base64,hashlib,io,re,warnings
from PIL import Image,UnidentifiedImageError
MAX_BYTES=5*1024*1024
MAX_PIXELS=20_000_000

def validate_upload(value):
    if not isinstance(value,str) or len(value)>MAX_BYTES*4//3+128:raise ValueError('请选择5MB以内的图片')
    m=re.fullmatch(r'data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)',value)
    if not m:raise ValueError('仅支持PNG、JPG、WebP图片')
    try:
        data=base64.b64decode(m[2],validate=True)
        if not data or len(data)>MAX_BYTES:raise ValueError('图片超过5MB')
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                fmt=im.format;w,h=im.size
                if w*h>MAX_PIXELS or w<1 or h<1:raise ValueError('图片像素过大，请使用2000万像素以内的图片')
                if getattr(im,'n_frames',1)!=1:raise ValueError('请上传静态海报')
                im.verify()
            with Image.open(io.BytesIO(data)) as im:im.load()
        expected={'png':'PNG','jpeg':'JPEG','webp':'WEBP'}[m[1]]
        if fmt!=expected:raise ValueError('图片类型与内容不一致')
        return {'bytes':data,'extension':{'png':'png','jpeg':'jpg','webp':'webp'}[m[1]],'mime':'image/'+m[1],'sha256':hashlib.sha256(data).hexdigest()}
    except Exception as ex:
        if isinstance(ex,ValueError):raise
        raise ValueError('图片损坏或无法读取，请更换图片') from None
