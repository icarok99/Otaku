import json

from resources.lib.ui import client, control, source_utils
from six.moves import urllib_parse


class AllDebrid:
    def __init__(self):
        self.apikey = control.getSetting('alldebrid.apikey')
        self.agent_identifier = 'Otaku_Addon'
        self.base_url = 'https://api.alldebrid.com/v4/'
        self.cache_check_results = []

    def get(self, url, **params):
        params.update({'agent': self.agent_identifier})
        return client.request(urllib_parse.urljoin(self.base_url, url), params=params, error=True)

    def post(self, url, post_data=None, **params):
        params.update({'agent': self.agent_identifier})
        return client.request(urllib_parse.urljoin(self.base_url, url), post=post_data, params=params, error=True)

    @staticmethod
    def _extract_data(response):
        if 'data' in response:
            return response['data']
        else:
            return response

    def get_json(self, url, **params):
        return self._extract_data(json.loads(self.get(url, **params)))

    def post_json(self, url, post_data=None, **params):
        post_ = self.post(url, post_data, **params)
        if not post_:
            return
        return self._extract_data(json.loads(post_))

    def auth(self):
        resp = self.get_json('pin/get')
        expiry = pin_ttl = int(resp['expires_in'])
        auth_complete = False
        control.copy2clip(resp['pin'])
        control.progressDialog.create(
            control.ADDON_NAME + ': AllDebrid Auth',
            control.lang(30100).format(control.colorString(resp['base_url'])) + '[CR]'
            + control.lang(30101).format(control.colorString(resp['pin'])) + '[CR]'
            + control.lang(30102)
        )

        control.progressDialog.update(100)
        while not auth_complete and not expiry <= 0 and not control.progressDialog.iscanceled():
            control.sleep(5 * 1000)
            auth_complete, expiry = self.poll_auth(check=resp['check'], pin=resp['pin'])
            progress_percent = 100 - int((float(pin_ttl - expiry) / pin_ttl) * 100)
            control.progressDialog.update(progress_percent)
            control.sleep(1 * 1000)
        try:
            control.progressDialog.close()
        except:
            pass

        if auth_complete:
            self.store_user_info()
            control.ok_dialog(control.ADDON_NAME, 'AllDebrid {}'.format(control.lang(30103)))
        else:
            return

    def poll_auth(self, **params):
        resp = self.get_json('pin/check', **params)
        if resp['activated']:
            control.setSetting('alldebrid.apikey', resp['apikey'])
            self.apikey = resp['apikey']
            return True, 0

        return False, int(resp['expires_in'])

    def store_user_info(self):
        user_information = self.get_json('user', apikey=self.apikey)
        if user_information is not None:
            control.setSetting('alldebrid.username', user_information['user']['username'])

    def upload_magnet(self, magnet_hash):
        result = self.get_json('magnet/upload', apikey=self.apikey, magnets=magnet_hash)
        magnets = result.get('magnets')
        magnet = [m for m in magnets if magnet_hash in m.get('magnet')]
        if magnet:
            magnet_id = magnet[0].get('id')
            if not magnet[0].get('ready'):
                self.delete_magnet(magnet_id)
                return
            return magnet_id
        return

    def update_relevant_hosters(self):
        return

    def get_hosters(self, hosters):
        host_list = self.update_relevant_hosters()
        if host_list is not None:
            hosters['premium']['all_debrid'] = \
                [(d, d.split('.')[0])
                 for x in list(host_list['hosts'].values())
                 if 'status' in x and x['status']
                 for d in x['domains']]
        else:
            hosters['premium']['all_debrid'] = []

    def resolve_hoster(self, url):
        resolve = self.get_json('link/unlock', apikey=self.apikey, link=url)
        return resolve['link']

    def magnet_status(self, magnet_id):
        return self.get_json('magnet/status', apikey=self.apikey, id=magnet_id)

    def list_torrents(self):
        return self.get_json('user/links', apikey=self.apikey)

    def link_info(self, url):
        return self.get_json('link/infos', apikey=self.apikey, link=url)

    def resolve_single_magnet(self, hash_, magnet, episode='', pack_select=False):
        selected_file = None

        magnet_id = self.upload_magnet(magnet)
        if not magnet_id:
            return
        folder_details = self.magnet_status(magnet_id)['magnets']['links']
        folder_details = [{'link': x['link'], 'path': x['filename']} for x in folder_details]

        if episode:
            selected_file = source_utils.get_best_match('path', folder_details, episode, pack_select)
            self.delete_magnet(magnet_id)
            if selected_file is not None:
                return self.resolve_hoster(selected_file['link'])

        selected_file = folder_details[0].get('link')

        if selected_file is None:
            return

        self.delete_magnet(magnet_id)
        return self.resolve_hoster(selected_file)

    def delete_magnet(self, magnet_id):
        return self.get_json('magnet/delete', apikey=self.apikey, id=magnet_id)
