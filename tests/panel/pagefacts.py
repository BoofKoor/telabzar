"""متنِ **دیدنیِ** یک صفحه — برای ادعاهایی که باید از بازطراحی جان سالم ببرند.

## چرا این هلپر هست

گامِ ۳ (/health) و گامِ ۵ (بازطراحیِ کامل) قرار است قالب‌ها را بازآرایی کنند.
تستی که مارک‌آپ را پین کند در آن گام **مالیات** است نه نگهبان: با هر جابه‌جاییِ
کارت قرمز می‌شود بی‌آنکه چیزی خراب شده باشد، و نتیجه‌اش این است که کسی حذفش
می‌کند. پس ادعاها روی «صفحه این واقعیت را **می‌گوید**» بسته می‌شوند نه روی
«این واقعیت داخلِ فلان `<div>` است»: بازآرایی سبز می‌ماند، افتادنِ واقعیت قرمز.

## چرا فقط `strip_tags` کافی نیست — تلهٔ ثبت‌شده در §۶

هر گاردی که متن را اسکن می‌کند سرانجام **توضیحاتِ خودش** را اسکن می‌کند. سه
نمونهٔ ثبت‌شده: دو گاردِ ASTی که `@needs_7z`ِ داخلِ داکس‌استرینگِ خودشان را
می‌شمردند، و — نزدیک‌ترین به این‌جا — گاردِ کلاسِ CSS که `.err` را از داخلِ
**کامنتِ فارسیِ بالای همان قاعده** می‌خواند و «تعریف‌شده» می‌دید. آن سابوتاژ
«نگرفت» گزارش شد در حالی که خرابکاری کاملاً اعمال شده بود.

قاعده دربارهٔ **ورودی** است نه پارسر: هر زبانی که اسکن می‌شود باید اول از
«متنِ دربارهٔ کد»ِ همان زبان پاک شود. این‌جا سه کانال ارسال می‌شوند:

* `<style>` — و **۶ کامنتِ CSS** در `_CSS` هست که به مرورگر می‌روند. همان کانالی
  که یک‌بار گاردِ کلاس را کور کرد.
* `<script>` — امروز فقط اسکریپتِ درون‌خطیِ `/buttons`.
* `<!-- … -->` — امروز **صفر** تا، ولی بازطراحی می‌تواند اضافه کند، و آن روز
  کسی به این فایل سر نمی‌زند. (کامنتِ `{# … #}`ِ جینجا اصلاً رندر نمی‌شود.)

`test_pagefacts.py` هر سه را با کنترلِ منفی می‌زند، و آن کنترل‌ها مستقیماً
**خودارجاعی** را می‌سنجند — نه صرفاً «چک می‌تواند بیفتد»، که ادعای ضعیف‌تری
است و همان چیزی است که این تله را یک‌بار از کنترل رد کرد.

## ترتیبِ عملیات باربر است

تگ‌ها باید از متنِ **خام** شناخته شوند و entityها **بعد** باز شوند. برعکسش
متنی را که صفحه عمداً escape کرده می‌خورد: `&lt;b&gt;` اول به `<b>` تبدیل و بعد
به‌عنوان تگ حذف می‌شود. همان ترتیبی که `downloader.strip_html` هم دارد.

و تگ با **فاصله** جایگزین می‌شود نه رشتهٔ تهی: `<b>10</b><b>2</b>` نباید
«۱۰۲» خوانده شود، وگرنه ادعای «عددِ ۱۰۲ در صفحه هست» به‌شکلِ تصادفی سبز می‌شود.

## چیزی که `hidden` است هم دیدنی نیست (۲۰۲۶-۱۰-۰۹)

`/texts` از این تاریخ **همهٔ** متن‌ها را رندر می‌کند و فیلتر فقط ردیف را
`hidden` می‌کند (تا `panel.js` درجا فیلتر کند و ویرایشِ ذخیره‌نشده با عوض‌شدنِ
دسته گم نشود)؛ `/settings` از قبل همین شکل را داشت. پس «صفحه این را **نمی‌گوید**»
بدونِ کنار گذاشتنِ زیردرختِ `hidden` همیشه غلط می‌شد — جست‌وجویی که هیچ ردیفی را
کنار نگذارد سبز می‌ماند. محتوای `<template>` هم دیدنی نیست (الگوی خام است).
این‌ها با شمارشِ **همان تگ** کنار گذاشته می‌شوند، نه با regex: زیردرختِ تودرتو
(`<div hidden><div>…</div></div>`) باید کامل برود و همسایه‌اش بماند.
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

__all__ = ["page_text", "missing_facts", "shows", "drop_hidden"]

_DROP = re.compile(r"<!--.*?-->|<style[^>]*>.*?</style>|<script[^>]*>.*?</script>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "source", "track", "wbr"})


class _Visible(HTMLParser):
    """مارک‌آپ را همان‌طور که هست پس می‌دهد، منهای زیردرخت‌های `hidden` و `<template>`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.skip: str | None = None    # تگی که زیردرختش کنار می‌رود
        self.depth = 0                  # تودرتوییِ همان تگ داخلِ خودش

    def handle_starttag(self, tag, attrs):
        if self.skip:
            self.depth += tag == self.skip
            return
        if (tag == "template" or any(k == "hidden" for k, _v in attrs)) and tag not in _VOID:
            self.skip, self.depth = tag, 1
            self.out.append(" ")    # جای خالیِ زیردرخت، مثلِ هر تگ: دو همسایه به هم نچسبند
            return
        if not any(k == "hidden" for k, _v in attrs):
            self.out.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        if not self.skip and not any(k == "hidden" for k, _v in attrs):
            self.out.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip:
                self.depth -= 1
                if not self.depth:
                    self.skip = None
            return
        self.out.append(f"</{tag}>")

    def _raw(self, text: str) -> None:
        if not self.skip:
            self.out.append(text)

    def handle_data(self, data):
        self._raw(data)

    def handle_entityref(self, name):
        self._raw(f"&{name};")

    def handle_charref(self, name):
        self._raw(f"&#{name};")

    def handle_comment(self, data):
        self._raw(f"<!--{data}-->")

    def handle_decl(self, decl):
        self._raw(f"<!{decl}>")


def drop_hidden(html: str) -> str:
    """همان HTML، بی زیردرخت‌هایی که مرورگر نشان نمی‌دهد (`hidden`، `<template>`)."""
    p = _Visible()
    p.feed(html)
    p.close()
    return "".join(p.out)


def page_text(html: str) -> str:
    """چیزی که کاربر واقعاً می‌خواند: بدونِ کامنت، استایل، اسکریپت، تگ و بخشِ پنهان."""
    without_noise = _DROP.sub(" ", drop_hidden(html))
    without_tags = _TAG.sub(" ", without_noise)
    return _WS.sub(" ", _html.unescape(without_tags)).strip()


def missing_facts(html: str, facts) -> list[str]:
    """آن‌هایی از `facts` که صفحه **نمی‌گوید** — به همان ترتیبِ ورودی."""
    text = page_text(html)
    return [str(f) for f in facts if str(f) not in text]


def shows(html: str, *facts) -> None:
    """assertِ خوانا: صفحه باید هر کدام از این‌ها را بگوید."""
    missing = missing_facts(html, facts)
    assert not missing, (
        f"صفحه این واقعیت‌ها را رندر نکرد: {missing}\n"
        f"— متنِ دیدنی: {page_text(html)[:400]}…")
