#!/usr/bin/env python3
# -*- coding:utf8 -*-

# Reads calendar dates from ical and creates an html based on given template.html.
#
# python3.7 ical.py --summary  -- calendar view including links
# python3.7 ical.py --full     -- calendar view including description

import datetime
import html
import re
import sys
import urllib.request
import uuid

import dateutil.parser
import dateutil.rrule
import dateutil.tz
import markdown

default_url = "https://caldav.hasi.it/c3si/all/"

special_format = """\
<div class="event">
  <div class="date center">
    <span class="center">
      <span class="bubble-event-day">{datetime:%a}</span>
      <span class="bubble-event-date">{datetime:%d.%m.}</span>
    </span>
  </div>
  {image:<div class="event-image" style="background-image: url(%s)"></div>}
  <div class="event-main">
    {summary:html:<h2>%s</h2>}
    <p class="event-time-place">
      <i class="fa fa-clock-o event-icon"></i> {datetime:%Y-%m-%d %H:%M}
      {location:html:<br><i class="fa fa-map-marker event-icon"></i> %s}
    </p>
    {description:md:%s}
    {follow_ups:html:<p><em>Folgetermine:</em> %s</p>}
  </div>
</div>\
"""

shortdesc_markdown_format = """\
* __{datetime:%d. %m. %Y}__ <a name="summary-{uid:%s}" href="#item-{uid:%s}">{summary:%s}</a>
"""

longdesc_markdown_format = """\

<article class="post-card post ">
    <a class="post-card-image-link" href="item-{uid:%s}">
        <div class="post-card-image" <!-- style="background-image: url(https://images.unsplash.com/photo-1526892523967-3e939630b835?ixlib&#x3D;rb-1.2.1&amp;q&#x3D;80&amp;fm&#x3D;jpg&amp;crop&#x3D;entropy&amp;cs&#x3D;tinysrgb&amp;w&#x3D;1080&amp;fit&#x3D;max&amp;ixid&#x3D;eyJhcHBfaWQiOjExNzczfQ)" -->></div>
    </a>
    <div class="post-card-content">
        <a class="post-card-content-link" href="item-{uid:%s} {description:%s}">
            <header class="post-card-header">
                <span class="post-card-tags">{datetime:__%d. %m. %Y, %H:%M Uhr__} {location:_Ort:_ %s}</span>
                <h2 class="post-card-title">{summary:html:%s}</h2>
            </header>
            <section class="post-card-excerpt">
                <p>{description:%s}</p>
            </section>
        </a>
        <footer class="post-card-meta">

            <ul class="author-list">
                <li class="author-list-item">

                    <div class="author-name-tooltip">
                        {datetime:__%d. %m. %Y, %H:%M Uhr__}
                    </div>

                    <!--<a href="/author/tau/" class="static-avatar"><img class="author-profile-image" src="/content/images/2019/01/tau-3.png" alt="Karsten &quot;Tau&quot; Hiekmann" /></a>-->
                </li>
            </ul>

            <span class="reading-time">{follow_ups:Folgetermine: %s}</span>-

        </footer>
    </div>
</article>

<!--
## <a name="item-{uid:%s}" href="#summary-{uid:%s}">{summary:html:%s}</a>

{datetime:__%d. %m. %Y, %H:%M Uhr__}

{description:%s}

{location:_Ort:_ %s}

{follow_ups:_Folgetermine:_ %s}
-->
"""

calendars = {}

# figure out the day start in local time
now = datetime.datetime.now( dateutil.tz.tzlocal() )
now = now.replace( hour=0, minute=0, second=0, microsecond=0 )
now = now.astimezone( dateutil.tz.tzutc() )


def simple_tzinfos(abbrev, offset):
    if not abbrev and not offset:
        return dateutil.tz.tzlocal()
    elif abbrev == "UTC" and offset == 0:
        return dateutil.tz.tzutc()
    else:
        print( "simple_tzinfos:", abbrev, offset )
    return 0


class FmtString( str ):
    def __format__(self, format_spec):
        if not self or not format_spec:
            return self

        if format_spec[:5] == "html:":
            return format_spec[5:] % html.escape( self )
        elif format_spec[:3] == "md:":
            return format_spec[3:] % markdown.markdown( self, safe_mode="escape" )
        else:
            return format_spec % self


class Event( dict ):
    def __init__(self, entries):
        for k, v in entries.items():
            self[k] = v
        self.upd = None

    def set_update_events(self, updates):
        if len( updates ) > 0:
            self.upd = updates[0]
            self.upd.set_update_events( updates[1:] )

    def get_ical(self, filter=None):
        pass

    def __getitem__(self, key):
        val = super( Event, self ).get( key, None )
        if val is None:
            tim, evt = self.get_time()[0]
            if key == 'datetime':
                val = tim
            elif key == 'uid':
                val = FmtString( evt["UID"] )
            elif key == 'summary':
                val = FmtString( evt["SUMMARY"] )
            elif key == 'description':
                val = FmtString( evt["DESCRIPTION"] )
            elif key == 'location':
                val = FmtString( evt["LOCATION"] )
            elif key == 'image':
                val = FmtString( "" )
            elif key == 'follow_ups':
                val = ""
                pending = self.get_time()[1:]
                if pending:
                    val = ", ".join( [p[0].strftime( "%d. %m. %Y" )
                                      for p in pending[:3]] ) + [".", "…"][len( pending ) > 3]
                val = FmtString( val )

        return val

    def __setitem__(self, key, value):
        rdict = {'n': "\n"}
        value = re.sub( "\\\\(.)",
                        lambda x: rdict.get( x.group( 1 ), x.group( 1 ) ), value )
        super( Event, self ).__setitem__( key, value )

    def __lt__(self, other):
        owntimes = self.get_time()
        othertimes = other.get_time()

        if len( owntimes ) > 0 and len( othertimes ) > 0:
            return self.get_time()[0][0] < other.get_time()[0][0]
        elif len( othertimes ) > 0:
            return True
        elif len( owntimes ) > 0:
            return False
        else:
            return False

    def is_pending(self):
        owntimes = self.get_time()

        if len( owntimes ):
            return now < self.get_time()[0][0]
        else:
            return False

    def get_time(self, times=None):
        if times is None:
            times = []
        if "RECURRENCE-ID" in self:
            rec = dateutil.parser.parse( self["RECURRENCE-ID"],
                                         tzinfos=simple_tzinfos )
            times = [t for t in times if t[0] != rec]

        if "DTSTART" in self and "RRULE" in self:
            rr = dateutil.rrule.rrulestr( self.rrtext, tzinfos=simple_tzinfos )
            pending = rr.between( now, now + datetime.timedelta( 120 ) )
            times = times + [(p.astimezone( dateutil.tz.tzlocal() ), self)
                             for p in pending]

        elif "DTSTART" in self:
            dts = dateutil.parser.parse( self["DTSTART"], tzinfos=simple_tzinfos )
            times = times + [(dts.astimezone( dateutil.tz.tzlocal() ), self)]

        else:
            times = times + [(now.astimezone( dateutil.tz.tzlocal() ), self)]

        if self.upd:
            times = self.upd.get_time( times )

        times.sort()
        while len( times ) > 1 and times[0][0] < now:
            times = times[1:]

        return times


class Calendar( object ):
    def __init__(self, url=None):
        if not url:
            url = default_url

        self.url = url

        data = urllib.request.urlopen( self.url ).read()
        data = data.decode( 'utf-8' )

        # normalize line endings
        data = data.replace( "\r\n", "\n" )
        data = data.replace( "\n\r", "\n" )
        # ical continuation lines
        data = data.replace( "\n ", "" )

        lines = [l.strip() for l in data.split( "\n" )]

        self.eventdict = {}
        cur_event = None
        inhibit = None
        raw_rrtext = ""

        for l in lines:
            if not l:
                continue

            key, value = l.split( ":", 1 )

            if ";" in key:
                key, extra = key.split( ";", 1 )

            if key == "BEGIN" and value == "VEVENT":
                cur_event = {}
                raw_rrtext = ""
                continue
            elif key == "BEGIN":
                inhibit = value

            if inhibit is None and key in ["RRULE", "RRULE", "RDATE", "EXRULE", "EXDATE", "DTSTART"]:
                raw_rrtext = raw_rrtext + "%s:%s\n" % (key, value)

            if key == "END" and value == "VEVENT":
                if "UID" not in cur_event:
                    cur_event["UID"] = "%s" % uuid.uuid1()
                uid = cur_event["UID"]
                if uid not in self.eventdict:
                    self.eventdict[uid] = []
                self.eventdict[uid].append( Event( cur_event ) )
                self.eventdict[uid][-1].rrtext = raw_rrtext
                cur_event = None
                continue
            elif key == "END" and value == inhibit:
                inhibit = None

            if inhibit is None and cur_event is not None:
                cur_event[key] = value

        self.eventlist = []

        for id, ev in self.eventdict.items():
            ev.sort( key=lambda x: int( x.get( "SEQUENCE", "0" ) ) )
            ev[0].set_update_events( ev[1:] )
            self.eventlist.append( ev[0] )

        self.eventlist.sort()

    def get_formatted(self, template, limit=-1):
        el = [e for e in self.eventlist if e.is_pending()]
        if limit > 0:
            el = el[:limit]
        text = "\n".join( [template.format_map( e ) for e in el] )
        return text


def insert_ical_to_html_code(m):
    # TODO: What is m?
    args = m.group( 2 ).split()
    marker_type = "summary"
    limit = -1
    url = default_url

    if len( args ) >= 1:
        if ":" in args[0]:
            marker_type, limit = args[0].split( ":", 2 )
            limit = int( limit )
        else:
            marker_type = args[0]

    if len( args ) >= 2:
        url = args[1]

    if not url in calendars:
        calendars[url] = Calendar( url )

    if marker_type == "full":
        txtdata = calendars[url].get_formatted( longdesc_markdown_format, limit )
    else:
        txtdata = calendars[url].get_formatted( shortdesc_markdown_format, limit )

    txtdata = markdown.markdown( txtdata )

    return m.group( 1 ) + txtdata + m.group( 3 )


if __name__ == '__main__':
    if not sys.argv[1:]:
        calendar = Calendar()
        print( calendar.get_formatted( special_format ) )

    for filename in sys.argv[1:]:
        html_page_of_last_replacement = open( filename ).read()
        html_page_for_current_replacement = re.sub(
            # (?ims): re.IGNORECASE, re.MULTILINE, re.DOTALL
            # \s*: 0...n unicode whitespaces
            # \b: empty string bound of a word
            # (.*?): capture group of the minimal characters found possible
            # TODO .*?: not really sure. Simon Wizardry
            r'(?ims)(<!--\s*ical\b\s*(.*?)\s*-->).*?(<!--\s*/ical\s*-->)',
            insert_ical_to_html_code,
            html_page_of_last_replacement )

        if html_page_for_current_replacement != html_page_of_last_replacement:
            outf = open( filename, "w" )
            outf.write( html_page_for_current_replacement )
            outf.close()