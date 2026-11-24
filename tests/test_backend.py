import asyncio
import importlib.util
from pathlib import Path
import unittest
import aiohttp
from aiohttp import web

spec = importlib.util.spec_from_file_location('backend', Path(__file__).parents[1] / 'custom_components/nest_announcements/backend.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
GOOD = 'Codec: opus\nBytes sent: 79201\nFFmpeg exit code: 0\n'

class Tests(unittest.IsolatedAsyncioTestCase):
    def test_response(self):
        self.assertTrue(backend.parse_response(200, GOOD)['ok'])
        self.assertFalse(backend.parse_response(200, 'OK')['ok'])
        self.assertFalse(backend.parse_response(200, GOOD.replace('79201','0'))['ok'])
        self.assertFalse(backend.parse_response(200, GOOD.replace('code: 0','code: 1'))['ok'])
        self.assertEqual(backend.parse_response(403, GOOD)['reason'], 'provider_authorisation_error')
        self.assertFalse(backend.parse_response(500, GOOD)['ok'])
        self.assertFalse(backend.parse_response(302, GOOD)['ok'])
        self.assertTrue(backend.valid_url('http://127.0.0.1:8765/announcement'))
        self.assertFalse(backend.valid_url('http://user:pass@localhost/x'))
        self.assertFalse(backend.valid_url('file:///etc/passwd'))

    async def test_http_and_concurrency(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def play(request):
            entered.set()
            await release.wait()
            return web.Response(text=GOOD)
        app = web.Application()
        app.router.add_post('/announcement', play)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                client = backend.AnnouncementBackend(session, f'http://127.0.0.1:{port}/announcement', 5)
                task = asyncio.create_task(client.play())
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual((await client.play())['reason'], 'announcement_already_running')
                release.set()
                self.assertTrue((await task)['ok'])
                self.assertEqual(client.last_result['bytes_sent'], 79201)
                client.url += '/missing'
                self.assertFalse((await client.play())['ok'])
        finally:
            release.set()
            await runner.cleanup()

if __name__ == '__main__':
    unittest.main()
