import base64
import io

import pytest
from fastapi import HTTPException
from PIL import Image
from server.map_studio.assets import Upload, decode_image


def upload(data, mime='image/png'):
    return Upload(name='Example', altText='Example illustration', rights='Original artwork',
                  mimeType=mime, dataBase64=base64.b64encode(data).decode())


@pytest.mark.asyncio
async def test_raster_is_decoded_in_child_and_optimized_without_metadata():
    source = io.BytesIO()
    Image.new('RGB', (320, 160), 'red').save(source, 'PNG')
    original, processed, width, height = await decode_image(upload(source.getvalue()))
    assert original == source.getvalue()
    assert (width, height) == (320, 160)
    assert Image.open(io.BytesIO(processed)).format == 'WEBP'


@pytest.mark.asyncio
@pytest.mark.parametrize('payload,mime', [
    (b'not an image', 'image/png'),
    (b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><script>alert(1)</script></svg>', 'image/svg+xml'),
    (b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><image href="file:///etc/passwd"/></svg>', 'image/svg+xml'),
    (b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><path fill="url(https://example.com/a)"/></svg>', 'image/svg+xml'),
])
async def test_malformed_and_active_images_rejected(payload, mime):
    with pytest.raises(HTTPException) as error:
        await decode_image(upload(payload, mime))
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_svg_aspect_ratio_preserved():
    payload = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><rect width="100" height="50" fill="red"/></svg>'
    _, processed, width, height = await decode_image(upload(payload, 'image/svg+xml'))
    assert (width, height) == (100, 50)
    assert Image.open(io.BytesIO(processed)).size == (100, 50)


@pytest.mark.asyncio
async def test_oversized_image_rejected_before_decoder():
    with pytest.raises(HTTPException) as error:
        await decode_image(upload(b'x' * (5 * 1024 * 1024 + 1)))
    assert error.value.status_code == 413
