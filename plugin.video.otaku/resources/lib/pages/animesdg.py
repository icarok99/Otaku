import itertools
import pickle
import re
import difflib
from bs4 import BeautifulSoup, SoupStrainer
from functools import partial
from resources.lib.ui import database
from resources.lib.ui.BrowserBase import BrowserBase

class Sources(BrowserBase):
    _BASE_URL = 'https://animesdigital.org/'

    def get_sources(self, mal_id, episode):
        show = database.get_show(mal_id)
        kodi_meta = pickle.loads(show.get('kodi_meta'))
        print(f"[DEBUG] kodi_meta: {kodi_meta}")

        # Get name, ename, and season
        name = kodi_meta.get('name')
        ename = kodi_meta.get('ename')
        season = kodi_meta.get('season') or 1

        # Detect season from title if present
        season_pattern = r'(?i)(?:(season|temporada|s)\s*(\d+)|(\d+)(?:st|nd|rd|th)\s*(season|temporada|s))'
        for title in [name, ename]:
            if title:
                match = re.search(season_pattern, title)
                if match:
                    if match.group(2):  # For "Season 2"
                        season = int(match.group(2))
                    elif match.group(3):  # For "2nd Season"
                        season = int(match.group(3))
                    break
        print(f"[DEBUG] Título recebido: name={name}, ename={ename} | Temporada: {season}")

        self.season = season  # Set for use in _filter_by_similarity

        # Prepare a list of titles to try (only simplified versions)
        titles_to_try = []
        similarity_titles = []
        if ename:  # Prioritize ename as it's more likely to match website naming
            clean_ename = self._normalize_title(ename)
            base_ename = re.sub(r'\b(season|\d+(?:st|nd|rd|th)\s*season|temporada|s)\b.*', '', clean_ename, flags=re.IGNORECASE).strip()
            titles_to_try.append(self._build_search_title(base_ename, season))
            similarity_titles.append(ename)
            similarity_titles.append(base_ename + f" {season}")
        if name and name != ename:
            clean_name = self._normalize_title(name)
            base_name = re.sub(r'\b(season|\d+(?:st|nd|rd|th)\s*season|temporada|s)\b.*', '', clean_name, flags=re.IGNORECASE).strip()
            titles_to_try.append(self._build_search_title(base_name, season))
            similarity_titles.append(name)
            similarity_titles.append(base_name + f" {season}")

        print(f"[DEBUG] Títulos a serem buscados: {titles_to_try}")

        # Try each title until results are found
        sitems = []
        for search_title in titles_to_try:
            print(f"[DEBUG] Buscando com título: {search_title}")
            res = self._search_anime(search_title)
            if res:
                sitems = self._parse_search_results(res)
                print(f"[DEBUG] Itens retornados da busca: {len(sitems)}")
                for i, item in enumerate(sitems, 1):
                    print(f"    {i}. {item['title']} - {item['slug']} ({item['lang']})")
                if sitems:
                    break

        if not sitems:
            print(f"[DEBUG] Nenhum resultado encontrado com os títulos fornecidos.")
            return []

        # Use both original and simplified titles for similarity filtering
        slugs = self._filter_by_similarity(sitems, similarity_titles, threshold=0.75)

        print(f"[DEBUG] Slugs filtrados por similaridade: {len(slugs)}")
        for i, s in enumerate(slugs, 1):
            print(f"    {i}. {s[0]} ({s[1]})")

        all_results = []
        if slugs:
            print(f"[DEBUG] Iniciando processamento do episódio {episode}...")
            clean_title = self._normalize_title(name or ename)
            mapfunc = partial(self._process_ad, title=clean_title, episode=episode)
            all_results = list(map(mapfunc, slugs))
            all_results = list(itertools.chain(*all_results))

        print(f"[DEBUG] Total de fontes encontradas: {len(all_results)}")
        return all_results

    def _normalize_title(self, title):
        title = title.lower()
        # Replace specific patterns like "no.8" or "no. 8" with "no 8"
        title = re.sub(r'no\.(\s*)8', r'no 8', title)
        # Convert ordinals to plain numbers (e.g., "2nd" → "2") instead of removing them
        title = re.sub(r'(\d+)(?:st|nd|rd|th)\b', r'\1', title)
        # Trim after season indicator but preserve if it's part of the base title
        title = re.sub(r'\s+\b(season|temporada|s)\b\s*\d*\s*$', '', title).strip()  # Only trim trailing season
        # Replace other punctuation with spaces
        title = re.sub(r'[.\-_:]', ' ', title)
        title = re.sub(r'\s+', ' ', title).strip()
        return title

    def _build_search_title(self, title, season):
        """
        title: normalized title (lower, no punctuation)
        season: integer
        Always appends season number if >1, unless already ends with a number.
        """
        try:
            s = int(season)
        except Exception:
            return title

        if s > 1:
            # Check if title already ends with a number (e.g., "title 2")
            if not re.search(r'\b\d+\s*$', title):
                return f"{title} {s}"
        return title

    def _search_anime(self, title):
        headers = {'Referer': self._BASE_URL}
        # Search URL is /search/{title.replace(' ', '+')}/
        search_url = f"{self._BASE_URL}search/{title.replace(' ', '+')}/"
        print(f"[DEBUG] Fazendo request para: {search_url}")
        res = database.get(
            self._get_request,
            8,
            search_url,
            headers=headers
        )
        if not res and ':' in title:
            title = title.split(':')[0]
            print(f"[DEBUG] Tentando novamente sem subtítulo: {title}")
            search_url = f"{self._BASE_URL}search/{title.replace(' ', '+')}/"
            res = database.get(
                self._get_request,
                8,
                search_url,
                headers=headers
            )
        return res

    def _parse_search_results(self, html):
        soup = BeautifulSoup(html, "html.parser")
        # Search results are in divs with class 'itemA'
        sdivs = soup.find_all('div', class_='itemA')
        sitems = []
        for sdiv in sdivs:
            try:
                a = sdiv.find('a', href=True)
                if a:
                    slug = a['href']
                    if not slug.startswith('http'):
                        slug = self._BASE_URL + slug.lstrip('/')
                    title_elem = sdiv.find('span', class_='title_anime')
                    stitle = title_elem.text.strip() if title_elem else a.get('title', '').strip()
                    # Detect lang: Check 'title_anime' span for 'Dublado'
                    lang = 'DUB' if title_elem and 'dublado' in title_elem.text.lower() else 'SUB'
                    sitems.append({'title': stitle, 'slug': slug, 'lang': lang})
            except AttributeError:
                pass
        return sitems

    def _similarity(self, a, b):
        score = difflib.SequenceMatcher(None, self._normalize_title(a), self._normalize_title(b)).ratio()
        return score

    def _filter_by_similarity(self, sitems, titles, threshold=0.75):
        best_matches = []
        for item in sitems:
            max_score = 0
            for t in titles:
                if t:
                    score = self._similarity(item['title'], t)
                    # Boost score if the item title contains the expected season number
                    if str(self.season) in item['title']:
                        score += 0.1  # Small boost to prefer season matches
                    print(f"[DEBUG] Similaridade '{item['title']}' vs '{t}': {score:.2f}")
                    if score > max_score:
                        max_score = score
            if max_score >= threshold:
                best_matches.append((item['slug'], item['lang'], max_score))

        best_matches.sort(key=lambda x: x[2], reverse=True)
        if not best_matches:
            print("[DEBUG] Nenhum item passou no filtro de similaridade.")
        return [(slug, lang) for slug, lang, _ in best_matches]

    def _process_ad(self, slug, title, episode):
        url, lang = slug
        print(f"[DEBUG] Processando slug: {url} - Lang: {lang}")
        sources = []
        headers = {'Referer': self._BASE_URL}
        page_num = 1
        episode_found = False
        episode_link = None

        while not episode_found:
            # Anime page with pagination: /anime/slug/page/{page_num}/?odr=1
            anime_page_url = f"{url}?odr=1"
            if page_num > 1:
                anime_page_url = f"{url}/page/{page_num}/?odr=1"
            print(f"[DEBUG] Verificando página {page_num}: {anime_page_url}")
            res = database.get(
                self._get_request,
                8,
                anime_page_url,
                headers=headers
            )
            if not res:
                print(f"[DEBUG] Falha ao carregar página {page_num}")
                break

            soup = BeautifulSoup(res, "html.parser")
            # Episode items are divs with class 'item_ep'
            episode_divs = soup.find_all('div', class_='item_ep')
            episode_items = [div.find('a', href=re.compile(r'/video/')) for div in episode_divs if div.find('a', href=re.compile(r'/video/'))]
            print(f"[DEBUG] Total de links de episódio na página {page_num}: {len(episode_items)}")

            for item in episode_items:
                # Get ep_text from title_anime div for precision
                title_elem = item.find('div', class_='title_anime')
                if title_elem:
                    ep_text = title_elem.text.strip().lower()
                else:
                    ep_text = item.text.strip().lower()
                print(f"[DEBUG] Texto do link: '{ep_text}' | href: {item.get('href')}")

                # Try different episode number formats, handling leading zero
                episode_patterns = [
                    rf'\b0?{episode}\b',  # Exact match: "3" or "03"
                    rf'\bep\.?\s*0?{episode}\b',  # "Ep 3" or "Ep. 3" or "Ep 03"
                    rf'\bepisode\s*0?{episode}\b',  # "Episode 3" or "Episode 03"
                    rf'\bepis[óo]dio\s*0?{episode}\b',  # "Episódio 3" (Portuguese) or "Episódio 03"
                    rf'\b0?{episode}\s*$'  # Ends with "3" or "03" (with possible leading space)
                ]
                for pattern in episode_patterns:
                    if re.search(pattern, ep_text, re.IGNORECASE):
                        episode_link = item['href']
                        if not episode_link.startswith('http'):
                            episode_link = self._BASE_URL + episode_link.lstrip('/')
                        episode_found = True
                        print(f"[DEBUG] Episódio {episode} encontrado: {episode_link}")
                        break
                if episode_found:
                    break

            if episode_found:
                break

            # Check for next page link
            next_link = soup.find('a', rel='next') or soup.find('a', string=re.compile(r'próxim|next', re.I))
            if not next_link or not next_link.get('href'):
                print(f"[DEBUG] Nenhuma página seguinte encontrada após página {page_num}")
                break
            page_num += 1

        if not episode_found:
            # Log available episodes from last page
            available_episodes = []
            for item in episode_items:
                title_elem = item.find('div', class_='title_anime')
                if title_elem:
                    available_episodes.append(title_elem.text.strip())
                else:
                    available_episodes.append(item.text.strip())
            print(f"[DEBUG] Episódio {episode} não encontrado. Episódios disponíveis na última página: {available_episodes}")
            return sources

        # Now process the episode page
        print(f"[DEBUG] Carregando página do episódio: {episode_link}")
        ep_html = self._get_request(episode_link, headers=headers)
        if not ep_html:
            print(f"[DEBUG] Falha ao carregar página do episódio")
            return sources

        # Extract video source from episode page
        slink = None
        soup_ep = BeautifulSoup(ep_html, "html.parser")
        # Look for iframe
        iframe = soup_ep.find('iframe', src=True)
        if iframe:
            iframe_src = iframe['src']
            if not iframe_src.startswith('http'):
                iframe_src = self._BASE_URL + iframe_src.lstrip('/')
            print(f"[DEBUG] Iframe encontrado: {iframe_src}")
            # Fetch iframe content
            iframe_html = self._get_request(iframe_src, headers=headers)
            if iframe_html:
                # Look for video file in JS, e.g., sources: [{file: 'url'}]
                m = re.search(r'sources:\s*\[.+?file:\s*[\'"]([^\'"]+)[\'"]', iframe_html, re.DOTALL | re.IGNORECASE)
                if m:
                    slink = m.group(1)
                else:
                    # Or direct source in iframe
                    m = re.search(r'<source\s+src=[\'"]([^\'"]+)[\'"]', iframe_html, re.IGNORECASE)
                    if m:
                        slink = m.group(1)
        if not slink:
            # Direct video tag
            video = soup_ep.find('video')
            if video:
                source = video.find('source', src=True)
                if source:
                    slink = source['src']

        if slink:
            print(f"[DEBUG] Link final encontrado: {slink}")
            source = {
                'release_title': f'{title} - Ep {episode}',
                'hash': f'{slink}|Referer={self._BASE_URL}',
                'type': 'direct',
                'quality': 0,
                'debrid_provider': '',
                'provider': 'animesdigital',
                'size': 'NA',
                'byte_size': 0,
                'info': [lang],
                'channel': 3,
                'sub': 1,
                'lang': 3 if lang == 'DUB' else 2
            }
            sources.append(source)
        else:
            print(f"[DEBUG] Nenhum link de vídeo encontrado para o episódio {episode} neste slug.")
        return sources