import os
import sqlite3
import re

from .db import get_db

import json

from flask import Flask, render_template, abort, g, redirect, Response, current_app, request

from indexer.util import mandoc_convert

def _quicksearch(man_section_lang):
    name, section, lang = _parse_man_name_section_lang(man_section_lang)
    return _get_manpage(name, section, lang)


def _get_package(name, repo):
    db = get_db().cursor()
    db.execute("""SELECT * FROM arch_packages
    WHERE NAME = ? AND REPO = ?""", (name, repo,))
    return db.fetchone()

def _parse_man_name_section_lang(url_snippet, force_lang=None):
# Man page names can contain dots, so we need to parse from the right. There are still
    # some ambiguities for shortcuts like gimp-2.8 (shortcut for gimp-2.8(1)), jclient.pl
    # (shortcut for jclient.pl.1.en) etc., but we'll either detect that the page given by
    # the greedy algorithm does not exist or the user can specify the section or language
    # to get the version they want.
    # NOTE: The force_lang parameter can be used to ignore the lang specified in the URL.
    # This is useful for redirections to the default language if we find out that there
    # is no version of the page in the user-specified language.
    parts = url_snippet.split(".")
    if len(parts) == 1:
        # name
        return url_snippet, None, None
    name = ".".join(parts[:-1])
    # the last part can be a section or a language
    if _exists_name_section(name, parts[-1]):
        # any.name.section: language cannot come before section, so we're done
        return name, parts[-1], None
    elif len(parts) == 2:
        if force_lang is not None and not _exists_language(parts[-1]):
            # we still need to validate the input
            return url_snippet, None, None
        if _exists_name_language(name, force_lang or parts[-1]):
            # name.lang
            return name, None, force_lang or parts[-1]
        else:
            # dotted.name
            return url_snippet, None, None
    elif _exists_language(parts[-1]):
        name2 = ".".join(parts[:-2])
        if _exists_name_section_language(name2, parts[-2], force_lang or parts[-1]):
            # name.section.lang
            return name2, parts[-2], force_lang or parts[-1]
        if _exists_name_language(name, force_lang or parts[-1]):
            # name.with.dots.lang
            return name, None, force_lang or parts[-1]
        # name.with.dots
        return url_snippet, None, None
    else:
        # name.with.dots
        return url_snippet, None, None

def _exists_name_section(name, section):
    db = get_db().cursor()
    db.execute("""SELECT EXISTS(SELECT 1 FROM arch_manpages WHERE NAME= ? AND SECTION = ? LIMIT 1);""", (name, section,))
    res1 = db.fetchone()[0]
    db.execute("""SELECT EXISTS(SELECT 1 FROM arch_redirects WHERE SOURCE_NAME = ? AND SOURCE_SECTION = ? LIMIT 1);""", (name, section,))
    res2 = db.fetchone()[0]
    return res1 == 1 or res2 == 1

def _exists_language(lang):
    db = get_db().cursor()
    db.execute("""SELECT EXISTS(SELECT 1 FROM arch_manpages WHERE LOCALE = ? LIMIT 1);""", (lang,))
    res = db.fetchone()[0]
    return res == 1

def _exists_name_language(name, lang):
    db = get_db().cursor()
    db.execute("""SELECT EXISTS(SELECT 1 FROM arch_manpages WHERE NAME = ? AND LOCALE = ? LIMIT 1);""", (name, lang,))
    res = db.fetchone()[0]
    return res == 1

def _exists_name_section_language(name, section, lang):
    db = get_db().cursor()
    db.execute("""SELECT EXISTS(SELECT 1 FROM arch_manpages WHERE NAME = ? AND SECTION = ? AND LOCALE = ? LIMIT 1);""", (name, section, lang,))
    res1 = db.fetchone()[0]
    db.execute("""SELECT EXISTS(SELECT 1 FROM arch_redirects WHERE SOURCE_NAME = ? AND SOURCE_SECTION = ? AND SOURCE_LANG = ? LIMIT 1);""", (name, section, lang,))
    res2 = db.fetchone()[0]

    return res1 == 1 or res2 == 1


def _get_manpage(name, section=None, lang=None):
    """
    Fetch manpage row from database
    """
    # Big brain?
    db = get_db().cursor()
    values = tuple(x for x in (name,section,lang,) if x is not None)
    db.execute(f"""SELECT * FROM arch_manpages
    WHERE NAME = ? {"AND SECTION = ?" if section else ""} {"AND LOCALE = ?" if lang else ""}""", values)
    result = db.fetchone()
    return result # may be None

# flask

def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config.from_mapping(
        SECRET_KEY='dev',
        DATABASE=os.path.join(os.path.dirname(__file__), '../packages.db'),
    )

    from . import db
    db.init_app(app)

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    #try:
    #    os.makedirs(app.instance_path)
    #except OSError:
    #    pass

    """
    @app.before_request
    def clear_trailing():
        rp = request.path 
        if rp != '/' and rp.endswith('/'):
            return redirect(rp[:-1])
    """

    index_content = """
    <article class="single-column-content">
        <section>
            <h1>Parabolas Manpages</h1>
            <p>This website contains a collection of manual pages from various pieces of software.</p>
            <ul>
                <li>Browse:
                    <ul>
                        <li><a href="by_section.html">by section</a></li>
                        <li><a href="by_alpha.html">alphabetically</a></li>
                        <li>by individual sections: 
                            <a href="section_0p.html">0p</a>, <a href="section_1.html">1</a>, <a href="section_1p.html">1p</a>, <a href="section_2.html">2</a>, <a href="section_3.html">3</a>, <a href="section_3p.html">3p</a>, <a href="section_4.html">4</a>, <a href="section_5.html">5</a>, <a href="section_6.html">6</a>, <a href="section_7.html">7</a>, <a href="section_8.html">8</a>
                        </li>
                    </ul>
                </li>
                <li>Intro pages
                    <br>
                    <a href="/man/intro.1.html">intro(1)</a>, <a href="/man/intro.2.html">intro(2)</a>, <a href="/man/intro.3.html">intro(3)</a>, <a href="/man/intro.4.html">intro(4)</a>, <a href="/man/intro.5.html">intro(5)</a>, <a href="/man/intro.6.html">intro(6)</a>, <a href="/man/intro.7.html">intro(7)</a>, <a href="/man/intro.8.html">intro(8)</a>
                </li>
                <li>Individual pages can be accessed using <pre><code>/man/&lt;name&gt;.&lt;section&gt;.html</code></pre></li>
            </ul>
        </section>
    </article>
    """
    @app.route('/')
    def index():
        return render_template("base.html", title="Home", content=index_content)

    @app.route('/about')
    def about():
        return "about"

    @app.route('/search')
    def search():
        query = request.args.get('q')
        go = (request.args.get('go') == "Go")
        result = _quicksearch(query)
        if result and go:
            return redirect(f"/man/{result['NAME']}.{result['SECTION']}")

        return "Not Implemented Yet"

    @app.route('/listing')
    def listing():
        db = get_db().cursor()
        db.execute("""SELECT * FROM arch_manpages
            ORDER BY
                NAME ASC;""")
        result = db.fetchall()
        #if not result:
            # not found
        return render_template("listing.html", manpages=result)


    @app.route('/man/<path:path>')
    def manpage(path):
        db = get_db().cursor()
        url_sections = path.split('/')
        if len(url_sections) > 1:
            abort(404)
            # TODO
        elif len(url_sections) == 1:
            url = url_sections[0]
            fmt = None
            # name.section.lang.format max(3)
            if url.count('.') > 3:
                abort(404)
            elif url.count('.') > 0 and url.rsplit('.', 1)[1] in ["html", "txt", "raw"]:
                # name.section.lang.format
                url, fmt = url.rsplit('.', 1)
            name, section, lang = _parse_man_name_section_lang(url)

        manpage = _get_manpage(name, section, lang)
        if manpage is None:
            abort(404)
        else:
            if section is None:
                # redirect: aio.h -> aio.h.0p
                return redirect(f"/man/{manpage['NAME']}.{manpage['SECTION']}" + (f".{fmt}" if fmt is not None else ""))
            else:
                if fmt is not None and fmt != "html": # html is handled by default
                    if fmt == "txt":
                        return Response(manpage['TXT_CONTENT'], mimetype='text/plain')
                    if fmt == "raw":
                        return Response(manpage['CONTENT'], mimetype='text/plain')
                name = manpage['NAME'] + '.' + manpage['SECTION']
                pkg = _get_package(manpage['PACKAGE'], manpage['REPO'])
                manpage = dict(manpage)
                manpage['HEADINGS'] = json.loads(manpage['HEADINGS'])
                return render_template('man-page.html', name=name, manpage=manpage, package=pkg,)

    @app.errorhandler(404)
    def page_not_found(error):
        return "not found", 404

    return app

if __name__ == "__main__":
    app.run()
