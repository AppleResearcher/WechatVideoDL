import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server_docker.thumbnail_service import create_thumbnail, validate_public_http_url


class FakeResponse:
    def __init__(self, *, status=200, headers=None, chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks or []

    def iter_content(self, chunk_size=65536):
        yield from self._chunks

    def close(self):
        pass


class ThumbnailServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def public_dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]

    def test_validate_public_https_accepts_public_host(self):
        with patch('server_docker.thumbnail_service.socket.getaddrinfo', self.public_dns):
            self.assertEqual(validate_public_http_url('https://img.example.com/a.jpg'), 'https://img.example.com/a.jpg')

    def test_validate_rejects_private_loopback_credentials_and_non_http(self):
        cases = [
            'file:///tmp/a.jpg',
            'https://user:pass@example.com/a.jpg',
            'https://127.0.0.1/a.jpg',
            'https://10.0.0.1/a.jpg',
            'https://169.254.1.1/a.jpg',
            'not-a-url',
        ]
        for url in cases:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_public_http_url(url)

    def test_cover_download_is_transcoded_to_jpeg(self):
        calls = []
        def http_get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(headers={'Content-Type': 'image/png'}, chunks=[b'fake-png'])

        def fake_run(cmd, **kwargs):
            Path(cmd[-1]).write_bytes(b'jpeg-output')
            class Result: returncode = 0; stderr = ''
            return Result()

        with patch('server_docker.thumbnail_service.socket.getaddrinfo', self.public_dns), \
             patch('server_docker.thumbnail_service.subprocess.run', fake_run):
            out = create_thumbnail(
                self.root, '标题__000001.jpg', 'https://img.example.com/a.png', None,
                http_get=http_get,
            )
        self.assertEqual(out, self.root / '标题__000001.jpg')
        self.assertEqual(out.read_bytes(), b'jpeg-output')
        self.assertEqual(calls[0][1]['allow_redirects'], False)

    def test_redirect_to_private_is_rejected_and_returns_none_without_video(self):
        def http_get(url, **kwargs):
            return FakeResponse(status=302, headers={'Location': 'http://127.0.0.1/private.jpg'})
        with patch('server_docker.thumbnail_service.socket.getaddrinfo', self.public_dns):
            out = create_thumbnail(
                self.root, '标题__000001.jpg', 'https://img.example.com/a.jpg', None,
                http_get=http_get,
            )
        self.assertIsNone(out)
        self.assertFalse((self.root / '标题__000001.jpg').exists())

    def test_response_size_cap_causes_cover_failure(self):
        def http_get(url, **kwargs):
            return FakeResponse(headers={'Content-Type': 'image/jpeg'}, chunks=[b'x' * 7, b'y' * 7])
        with patch('server_docker.thumbnail_service.socket.getaddrinfo', self.public_dns):
            out = create_thumbnail(
                self.root, '标题__000001.jpg', 'https://img.example.com/a.jpg', None,
                http_get=http_get, max_bytes=10,
            )
        self.assertIsNone(out)

    def test_cover_failure_falls_back_to_video_first_frame(self):
        video = self.root / '标题__000001.mp4'
        video.write_bytes(b'video')
        def http_get(url, **kwargs):
            raise OSError('network down')
        def fake_run(cmd, **kwargs):
            self.assertIn(str(video), cmd)
            Path(cmd[-1]).write_bytes(b'frame-jpeg')
            class Result: returncode = 0; stderr = ''
            return Result()
        with patch('server_docker.thumbnail_service.socket.getaddrinfo', self.public_dns), \
             patch('server_docker.thumbnail_service.subprocess.run', fake_run):
            out = create_thumbnail(
                self.root, '标题__000001.jpg', 'https://img.example.com/a.jpg', video,
                http_get=http_get,
            )
        self.assertEqual(out.read_bytes(), b'frame-jpeg')

    def test_ffmpeg_failure_returns_none_and_cleans_temps(self):
        video = self.root / '标题__000001.mp4'
        video.write_bytes(b'video')
        def fake_run(cmd, **kwargs):
            class Result: returncode = 1; stderr = 'bad'
            return Result()
        with patch('server_docker.thumbnail_service.subprocess.run', fake_run):
            out = create_thumbnail(self.root, '标题__000001.jpg', None, video)
        self.assertIsNone(out)
        self.assertFalse((self.root / '标题__000001.jpg').exists())
        self.assertEqual([p.name for p in self.root.iterdir()], [video.name])


if __name__ == '__main__':
    unittest.main()
