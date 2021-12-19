import logging

import subprocess

import sys

class CustomFormatter(logging.Formatter):

    blue = "\x1b[34m"
    yellow = "\x1b[33m"
    red = "\x1b[31;21m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: blue + format + reset,
        logging.INFO: blue + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

class ProgressBar(object):
    def __init__(self, total=100):
        self.current = 0
        self.total = total

    def print_bar(self):
        sys.stdout.write("\r")
        sys.stdout.flush()

## man2html (https://gitlab.archlinux.org/archlinux/archmanweb/-/blob/master/archmanweb/utils/mandoc.py) ##

def mandoc_convert(content):
    cmd = f"mandoc -T html -O fragment"
    p = subprocess.run(cmd, shell=True, check=True, input=content, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stdout

# function copied from wiki-scripts:
# https://github.com/lahwaacz/wiki-scripts/blob/master/ws/parser_helpers/encodings.py#L81-L98
def _anchor_preprocess(str_):
    """
    Context-sensitive pre-processing for anchor-encoding. See `MediaWiki`_ for
    details.

    .. _`MediaWiki`: https://www.mediawiki.org/wiki/Manual:PAGENAMEE_encoding
    """
    # underscores are treated as spaces during this pre-processing, so they are
    # converted to spaces first (the encoding later converts them back)
    str_ = str_.replace("_", " ")
    # strip leading + trailing whitespace
    str_ = str_.strip()
    # squash *spaces* in the middle (other whitespace is preserved)
    str_ = re.sub("[ ]+", " ", str_)
    # leading colons are stripped, others preserved (colons in the middle preceded by
    # newline are supposed to be fucked up in MediaWiki, but this is pretty safe to ignore)
    str_ = str_.lstrip(":")
    return str_

# adapted from `anchorencode` in wiki-scripts (the "legacy" format was removed):
# https://github.com/lahwaacz/wiki-scripts/blob/master/ws/parser_helpers/encodings.py#L119-L152
def anchorencode_id(str_):
    """
    anchorencode_id avoids percent-encoding to keep the id readable
    """
    str_ = _anchor_preprocess(str_)
    # HTML5 specification says ids must not contain spaces
    str_ = re.sub("[ \t\n\r\f\v]", "_", str_)
    return str_


def _replace_section_heading_ids(html):
    """
    Replace IDs for section headings and self-links with something sensible and wiki-compatible

    E.g. mandoc does not strip the "\&" roff(7) escape, may lead to duplicate underscores,
    and sometimes uses weird encoding for some chars.
    """
    # section ID getter capable of handling duplicate titles
    ids = set()
    def get_id(title):
        base_id = anchorencode_id(title)
        id = base_id
        j = 2
        while id in ids:
            id = base_id + "_" + str(j)
            j += 1
        ids.add(id)
        return id

    def repl_heading(match):
        heading_tag = match.group("heading_tag")
        heading_attributes = match.group("heading_attributes")
        heading_attributes = " ".join(a for a in heading_attributes.split() if not a.startswith("id="))
        title = match.group("title").replace("\n", " ")
        id = safe_escape_attribute(get_id(title))
        href = anchorencode_href(id, input_is_already_id=True)
        return f"<{heading_tag} {heading_attributes} id='{id}'><a class='permalink' href='#{href}'>{title}</a></{heading_tag}>"

    pattern = re.compile(r"\<(?P<heading_tag>h[1-6])(?P<heading_attributes>[^\>]*)\>[^\<\>]*"
                         r"\<a class=(\"|\')permalink(\"|\')[^\>]*\>"
                         r"(?P<title>.+?)"
                         r"\<\/a\>[^\<\>]*"
                         r"\<\/(?P=heading_tag)\>", re.DOTALL)
    return re.sub(pattern, repl_heading, html)


def postprocess(text):
    xref_pattern = re.compile(r"\<(?P<tag>b|i|strong|em|mark)\>"
                                  r"(?P<man_name>[A-Za-z0-9@._+\-:\[\]]+)"
                                  r"\<\/\1\>"
                                  r"\((?P<section>\d[a-z]{,3})\)")
    text = xref_pattern.sub("<a href='" + reverse("index") + "man/" + r"\g<man_name>.\g<section>." + lang +
                                    "'>\g<man_name>(\g<section>)</a>",
                            text)

    # remove empty tags
    text = re.sub(r"\<(?P<tag>[^ >]+)[^>]*\>(\s|&nbsp;)*\</(?P=tag)\>\n?", "", text)

    # strip leading and trailing newlines and remove common indentation
    # from the text inside <pre> tags
    _pre_tag_pattern = re.compile(r"\<pre\>(.+?)\</pre\>", flags=re.DOTALL)
    text = _pre_tag_pattern.sub(lambda match: "<pre>" + textwrap.dedent(match.group(1).strip("\n")) + "</pre>", text)

    # remove <br/> tags following a <pre> or <div> tag
    text = re.sub(r"(?<=\</(pre|div)\>)\n?<br/>", "", text)

    # replace URLs in plain-text with <a> links
    #text = _replace_urls_in_plain_text(text)

    # replace IDs for section headings and self-links with something sensible and wiki-compatible
    text = _replace_section_heading_ids(text)

    return text

def extract_headings(html):
    def normalize(title):
        return re.sub(r"\s+", " ", title)
    result = []
    headings_pattern = re.compile(r"\<h1[^\>]*\>[^\<\>]*"
                                  r"\<a class=(\"|\')permalink(\"|\') href=(\"|\')#(?P<id>\S+)(\"|\')\>"
                                  r"(?P<title>.+?)"
                                  r"\<\/a\>[^\<\>]*"
                                  r"\<\/h1\>", re.DOTALL)
    for match in headings_pattern.finditer(html):
        id = normalize_html_entities(match.group("id"))
        title = normalize_html_entities(normalize(match.group("title")))
        result.append(dict(id=id, title=title))
    return result

def extract_description(text, lang="en"):
    """
    Extracts the "description" from a plain-text version of a manual page.

    The description is taken from the NAME section (or a hard-coded list of
    translations for non-English manuals). At most 2 paragraphs, one of which
    is usually the one-line description of the manual, are taken to keep the
    description short.

    Note that NAME does not have to be the first section, see e.g. syslog.h(0P).
    """
    dictionary = {
        "ar": "الاسم",
        "bn": "নাম",
        "ca": "NOM",
        "cs": "JMÉNO|NÁZEV",
        "da": "NAVN",
        "de": "BEZEICHNUNG",
        "el": "ΌΝΟΜΑ",
        "eo": "NOMO",
        "es": "NOMBRE",
        "et": "NIMI",
        "fi": "NIMI",
        "fr": "NOM",
        "gl": "NOME",
        "hr": "IME",
        "hu": "NÉV",
        "id": "NAMA",
        "it": "NOME",
        "ja": "名前",
        "ko": "이름",
        "lt": "PAVADINIMAS",
        "nb": "NAVN",
        "nl": "NAAM",
        "pl": "NAZWA",
        "pt": "NOME",
        "ro": "NUME",
        "ru": "ИМЯ|НАЗВАНИЕ",
        "sk": "NÁZOV",
        "sl": "IME",
        "sr": "НАЗИВ|ИМЕ|IME",
        "sv": "NAMN",
        "ta": "பெயர்",
        "tr": "İSİM|AD",
        "uk": "НАЗВА|НОМИ|NOMI",
        "vi": "TÊN",
        "zh": "名称|名字|名称|名稱",
    }
    lang = lang.split("_")[0].split("@")[0]
    name = dictionary.get(lang, "NAME")
    if name != "NAME":
        name = "NAME|" + name
    match = re.search(rf"(^{name}$)(?P<description>.+?)(?=^\S)", text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if match is None:
        return None
    description = match.group("description")
    description = textwrap.dedent(description.strip("\n"))
    # keep max 2 paragraphs separated by a blank line
    # (some pages contain a lot of text in the NAME section, e.g. owncloud(1) or qwtlicense(3))
    description = "\n\n".join(description.split("\n\n")[:2])
    return description


# end man2html

def sizeof_fmt(size, decimal_places=2):
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']:
        if size < 1024.0 or unit == 'PiB':
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"