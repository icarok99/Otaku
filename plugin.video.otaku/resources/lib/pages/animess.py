import itertools
import pickle
import re
import difflib
from bs4 import BeautifulSoup, SoupStrainer
from functools import partial
from resources.lib.ui import database
from resources.lib.ui.BrowserBase import BrowserBase

class Sources(BrowserBase):
    _BASE_URL = 'https://animefhd.com/'

    def get_sources(self, mal_id, episode):
        show = database.get_show(mal_id)
        kodi_meta = pickle.loads(show.get('kodi_meta'))
        print(f"[DEBUG] kodi_meta: {kodi_meta}")

        # Get name, ename, and season
        name = kodi_meta.get('name')
        ename = kodi_meta.get('ename')
        season = kodi_meta.get('season') or 1

        # Detect season from title if present
        season_pattern = r'(?i)(?:(season|temporada|s)\s*(\d+)|(\d+)(?:st|nd|rd|th)\s*(season|temporada|s))|\s*(\d+)\s*$'
        for title in [name, ename]:
            if title:
                match = re.search(season_pattern, title)
                if match:
                    if match.group(2):  # For "Season 2"
                        season = int(match.group(2))
                    elif match.group(3):  # For "2nd Season"
                        season = int(match.group(3))
                    elif match.group(5):  # For trailing "2"
                        season = int(match.group(5))
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
            mapfunc = partial(self._process_am, title=clean_title, episode=episode)
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
        params = {'s': title}
        print(f"[DEBUG] Fazendo request com parâmetro s={title}")
        res = database.get(
            self._get_request,
            8,
            self._BASE_URL,
            data=params,
            headers=headers
        )
        if not res and ':' in title:
            title = title.split(':')[0]
            print(f"[DEBUG] Tentando novamente sem subtítulo: {title}")
            params.update({'s': title})
            res = database.get(
                self._get_request,
                8,
                self._BASE_URL,
                data=params,
                headers=headers
            )
        return res

    def _parse_search_results(self, html):
        mlink = SoupStrainer('div', {'class': re.compile('^SectionBusca')})
        mdiv = BeautifulSoup(html, "html.parser", parse_only=mlink)
        sdivs = mdiv.find_all('div', {'class': 'ultAnisContainerItem'})
        sitems = []
        for sdiv in sdivs:
            try:
                slug = sdiv.find('a').get('href')
                stitle = sdiv.find('a').get('title')
                lang = 'DUB' if 'dublado' in sdiv.find('div', {'class': 'aniNome'}).text.strip().lower() else 'SUB'
                sitems.append({'title': stitle, 'slug': slug, 'lang': lang})
            except AttributeError:
                pass
        return sitems

    def _similarity(self, a, b):
        score = difflib.SequenceMatcher(None, self._normalize_title(a), self._normalize_title(b)).ratio()
        return score

    def _filter_by_similarity(self, sitems, titles, threshold=0.75):
        best_matches = []
        season_pattern = r'(?i)(?:(season|temporada|s)\s*(\d+)|(\d+)(?:st|nd|rd|th)\s*(season|temporada|s))|\s*(\d+)\s*$'
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

            # Extract season from item title
            item_season = None
            match = re.search(season_pattern, item['title'])
            if match:
                if match.group(2):
                    item_season = int(match.group(2))
                elif match.group(3):
                    item_season = int(match.group(3))
                elif match.group(5):
                    item_season = int(match.group(5))

            # Decide whether to include based on season
            if item_season is not None:
                if item_season != self.season:
                    continue
            else:
                # Assume season 1 if no season detected
                if self.season != 1:
                    continue

            if max_score >= threshold:
                best_matches.append((item['slug'], item['lang'], max_score))

        best_matches.sort(key=lambda x: x[2], reverse=True)
        if not best_matches:
            print("[DEBUG] Nenhum item passou no filtro de similaridade.")
        return [(slug, lang) for slug, lang, _ in best_matches]

    def _process_am(self, slug, title, episode):
        url, lang = slug
        print(f"[DEBUG] Processando slug: {url} - Lang: {lang}")
        sources = []
        headers = {'Referer': self._BASE_URL}
        res = database.get(
            self._get_request,
            8,
            url,
            headers=headers
        )
        elink = SoupStrainer('div', {'class': 'sectionEpiInAnime'})
        ediv = BeautifulSoup(res, "html.parser", parse_only=elink)
        items = ediv.find_all('a')
        print(f"[DEBUG] Total de links <a> encontrados em sectionEpiInAnime: {len(items)}")
        for item in items:
            print(f"[DEBUG] Texto do link: '{item.text.strip()}' | href: {item.get('href')}")

        # Try different episode number formats
        episode_patterns = [
            rf'\b{episode}\b',  # Exact match: "3"
            rf'\bEp\.?\s*{episode}\b',  # "Ep 3" or "Ep. 3"
            rf'\bEpisode\s*{episode}\b',  # "Episode 3"
            rf'\bEpis[óo]dio\s*{episode}\b',  # "Episódio 3" (Portuguese)
            rf'\b{episode}\s*$'  # Ends with "3" (with possible leading space)
        ]
        e_id = []
        for pattern in episode_patterns:
            e_id.extend([x.get('href') for x in items if re.search(pattern, x.text, re.IGNORECASE)])
        print(f"[DEBUG] Episódios encontrados para episódio {episode}: {len(e_id)}")

        if not e_id:
            # Log available episodes
            available_episodes = [x.text.strip() for x in items if x.text.strip()]
            print(f"[DEBUG] Episódio {episode} não encontrado. Episódios disponíveis: {available_episodes}")
            return sources

        # Process the first matching episode link
        html = self._get_request(e_id[0], headers=headers)
        slink = re.search(r'<source\s*src="([^"]+)', html)
        if not slink:
            ilink = re.search(r'<iframe.+?src="([^"]+)', html)
            if ilink:
                html = self._get_request(ilink.group(1), headers=headers)
                slink = re.search(r'''sources:\s*\[{.+?file:\s*'([^']+)''', html, re.DOTALL)
        if not slink:
            elink = re.search(r'<div\s*id="Link".+?href="([^"]+)', html, re.DOTALL)
            if elink:
                html = self._get_request(elink.group(1), headers=headers)
                slink = re.search(r'''file:\s*['"]([^'"]+)''', html)
        if slink:
            print(f"[DEBUG] Link final encontrado: {slink.group(1)}")
            source = {
                'release_title': f'{title} - Ep {episode}',
                'hash': f'{slink.group(1)}|Referer={self._BASE_URL}',
                'type': 'direct',
                'quality': 0,
                'debrid_provider': '',
                'provider': 'animesfhd',
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