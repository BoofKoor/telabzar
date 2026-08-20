'use client'

import { C } from '@/lib/theme'
import { usePageData, type HealthPage } from '@/lib/api'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { PageState } from '@/components/ApiBanner'
import { Queue } from '@/components/Sidebar'
import { Bar, Empty, Fa, Flag, Head, Row } from '@/components/ui'
import { hueOf } from '@/lib/zones'

/**
 * ۰۳ HEALTH — «الان چه چیزی خراب است؟»
 *
 * مرزِ این صفحه با TRAFFIC عمدی است و در §۷ ثبت شده: این‌جا **لحظه‌ای** است
 * و آن‌جا **تاریخی**. پس هیچ نمودارِ روندی این‌جا نیست و هیچ سرویسی آن‌جا.
 *
 * دو کارت که در پنلِ فارسی هم هستند و این‌جا هم ماندند چون دقیقاً همان
 * سؤال‌های عملیاتی‌اند: نسخهٔ موتور (کهنه = «سشن را عوض نکن، آپدیت کن») و
 * جاب‌های گیرکرده (که Open Questions هنوز بازش می‌داند).
 */
export default function Page() {
  const state = usePageData<HealthPage>('health')
  const d = state.data
  const hosts = d?.hosts ?? []
  const engines = d?.health.engines ?? []
  const stuck = d?.stuck ?? []

  return (
    <Shell active="03" cmd="./ctl health --watch">
      {({ vals }) => (
        <>
          <div className="mx-trio" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(0,1fr))', gap: 18 }}>
            <Section
              label="SERVICES"
              sigil="◉"
              right={`${vals.services.length} checked`}
              corners
              pad="22px 14px 11px"
            >
              <PageState state={state}>
                {vals.services.map((s, i) => (
                  <Row key={s.name} last={i === vals.services.length - 1}>
                    <Flag text={s.flag} color={s.color} />
                    <span style={{ color: C.inkMid }}>{s.name}</span>
                    <span style={{ marginLeft: 'auto', color: C.inkLo, fontSize: 10 }}>{s.meta}</span>
                  </Row>
                ))}
              </PageState>
            </Section>

            <Queue queues={vals.queueRows} resources={vals.resources} />

            {/* فقط کل/مصرف واقعی است: تفکیکِ downloads/tmp/models هیچ‌جا
                محاسبه نمی‌شود، و ردیفِ ساختگی کنارِ ردیفِ واقعی از بیرون
                تفکیک‌ناپذیر است. */}
            <Section
              label="DISK · /work"
              sigil="▤"
              right={d?.health.disk_total ? `${d.health.disk_used}/${d.health.disk_total} GB` : '—'}
              pad="22px 14px 12px"
            >
              <PageState state={state}>
                {d?.health.disk_total ? (
                  <>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 9, fontSize: 11 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                        <span style={{ width: 74, color: C.ink }}>used</span>
                        <Bar
                          pct={d.health.disk_pct}
                          color={d.health.disk_pct > 85 ? C.warn : C.acc}
                        />
                        <span style={{ marginLeft: 'auto', color: C.inkHi }}>
                          {d.health.disk_used} GB
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                        <span style={{ width: 74, color: C.ink }}>free</span>
                        <Bar pct={100 - d.health.disk_pct} color={C.info} />
                        <span style={{ marginLeft: 'auto', color: C.inkHi }}>
                          {d.health.disk_total - d.health.disk_used} GB
                        </span>
                      </div>
                    </div>
                    <div
                      style={{
                        borderTop: `1px solid ${C.edgeHair}`,
                        marginTop: 11,
                        paddingTop: 10,
                        fontSize: 10,
                        color: C.inkDim,
                        lineHeight: 1.8,
                      }}
                    >
                      {d.health.disk_pct}% used · the download path refuses below dl_min_free_gb
                    </div>
                  </>
                ) : (
                  <Empty>WORK_DIR NOT READABLE</Empty>
                )}
              </PageState>
            </Section>
          </div>

          <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
            <Section label="DOWNLOAD RATE · TODAY (UTC)" sigil="↓" right="dlstat:*" pad="22px 14px 12px">
              <PageState state={state}>
                <Head cols={[{ w: 92, label: 'PLATFORM' }, { label: 'OK' }, { w: 96, label: 'OK / N', right: true }]} />
                {hosts.map((h, i) => {
                  const n = h.ok + h.fail
                  const col = h.rate >= 90 ? C.acc : h.rate >= 75 ? C.warn : C.bad
                  return (
                    <Row key={h.name} last={i === hosts.length - 1}>
                      <span style={{ width: 92, color: hueOf(h.name) }}>{h.name}</span>
                      <span style={{ flex: 1 }}>
                        <Bar pct={h.rate} width={16} color={col} />
                      </span>
                      <span style={{ width: 96, textAlign: 'right', color: col, whiteSpace: 'nowrap' }}>
                        {h.rate}% · {h.ok}/{n}
                      </span>
                    </Row>
                  )
                })}
                {!hosts.length && <Empty>NO DOWNLOADS TODAY</Empty>}
              </PageState>
              <div style={{ marginTop: 9, fontSize: 9.5, color: C.inkDim, letterSpacing: '.06em' }}>
                window = today UTC · dlstat TTL = 48h, so a raw KEYS scan double-counts
              </div>
            </Section>

            <Section label="ENGINE VERSIONS" sigil="⚙" right="dlver:*" pad="22px 14px 12px">
              <PageState state={state}>
                <Head cols={[{ w: 96, label: 'WHO' }, { w: 96, label: 'GALLERY-DL' }, { label: 'YT-DLP' }]} />
                {engines.map((e, i) => (
                  <Row key={e.who ?? i} last={i === engines.length - 1}>
                    <span style={{ width: 96, color: C.inkMid }}>{e.who ?? '—'}</span>
                    <span style={{ width: 96, color: C.inkLo }}>{e.gallerydl ?? '—'}</span>
                    <span style={{ flex: 1, color: C.inkLo }}>{e.ytdlp ?? '—'}</span>
                  </Row>
                ))}
                {/* «تازه یا کهنه؟» عمداً قضاوت نمی‌شود: مقایسه با آخرین نسخهٔ
                    منتشرشده یک درخواستِ شبکه به PyPI می‌خواهد که پنل نمی‌زند،
                    و یک بجِ حدسی بدتر از نبودش است. */}
                {!engines.length && <Empty>NO WORKER HAS REPORTED YET</Empty>}
              </PageState>
              <div style={{ marginTop: 10, fontSize: 10, color: C.inkDim, lineHeight: 1.8 }}>
                stale engine → <span style={{ color: C.accHi }}>node/update.sh</span> on that host.
                <br />
                current engine + login errors → replace the session, not the code.
              </div>
            </Section>
          </div>

          <Section
            label="STUCK JOBS" sigil="⏳"
            labelColor={C.warn}
            edge={C.auditEdge}
            bg={C.auditBg}
            right="age &gt; job_timeout"
            rightColor={C.warn}
            pad="22px 14px 12px"
          >
            <PageState state={state}>
              <Head cols={[{ w: 56, label: 'ID' }, { w: 116, label: 'OP' }, { w: 76, label: 'STATUS' }, { w: 90, label: 'AGE' }, { label: 'FILE' }]} />
              {stuck.map((j, i) => (
                <Row key={j.id} last={i === stuck.length - 1}>
                  <span style={{ width: 56, color: C.inkDim }}>#{j.id}</span>
                  <span style={{ width: 116, color: C.accHi }}>
                    <Fa>{j.op}</Fa>
                  </span>
                  <span style={{ width: 76, color: j.status === 'running' ? C.warn : C.inkDim }}>
                    {j.status}
                  </span>
                  <span style={{ width: 90, color: C.bad }}>
                    <Fa>{j.age}</Fa>
                  </span>
                  <span style={{ flex: 1, color: C.inkLo, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {j.file}
                  </span>
                </Row>
              ))}
              {!stuck.length && <Empty>NONE — every job finished inside its timeout</Empty>}
            </PageState>
            <div style={{ marginTop: 10, fontSize: 10, color: C.inkDim, lineHeight: 1.8 }}>
              `finally` does not run on SIGKILL, so a worker killed between `status=running` and its
              commit leaves the row forever. Nothing sweeps these today — Open Questions.
            </div>
          </Section>
        </>
      )}
    </Shell>
  )
}
