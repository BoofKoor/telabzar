'use client'

import { C } from '@/lib/theme'
import { NODE_ROWS } from '@/lib/pages'
import { Shell } from '@/components/Shell'
import { Section } from '@/components/Section'
import { Btn, Chip, Cmd, Flag, Head, Input, Row, Select } from '@/components/ui'

/**
 * ۰۴ NODES — ماشین‌های راه‌دور روی WireGuard.
 *
 * سه نقش، و تفاوتشان روی صفحه دیده می‌شود چون رفتارِ عملیاتی‌شان فرق دارد:
 * `download` و `processing` ورکرِ ARQ‌اند (صف دارند)، ولی `gateway` یک
 * پروکسیِ معکوس است و اصلاً صف ندارد — کارتی که هر سه را یک‌شکل نشان بدهد
 * این تفاوت را پنهان می‌کند.
 *
 * فرمانِ نصب یک توکنِ **یک‌بارمصرف** دارد، پس بعد از نمایش دیگر تکرارشدنی
 * نیست؛ به‌همین دلیل جعبه‌اش کنارِ خودِ فرم است نه پشتِ یک ریدایرکت.
 */
export default function Page() {
  const up = NODE_ROWS.filter((n) => n.up).length

  return (
    <Shell active="04" cmd="./ctl nodes --status" bits={false}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Chip color={up === NODE_ROWS.length ? C.acc : C.bad}>
          {up}/{NODE_ROWS.length} up
        </Chip>
        <Chip>wg0 10.51.0.0/24</Chip>
        <Chip>mtu 1420</Chip>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: C.inkDim, letterSpacing: '.1em' }}>
          peers are declarative · host wg-sync reconciles from the Node table
        </span>
      </div>

      <Section label="NODES" sigil="⎔" right="heartbeat ttl 45s" corners pad="22px 14px 12px">
        <Head
          cols={[
            { w: 46, label: '' },
            { w: 96, label: 'NAME' },
            { w: 96, label: 'ROLE' },
            { w: 96, label: 'WG IP' },
            { w: 60, label: 'RTT', right: true },
            { w: 56, label: 'JOBS', right: true },
            { w: 70, label: 'DONE', right: true },
            { label: 'SEEN', right: true },
          ]}
        />
        {NODE_ROWS.map((n, i) => (
          <Row key={n.id} last={i === NODE_ROWS.length - 1}>
            <Flag text={n.up ? '[ UP ]' : '[DOWN]'} color={n.up ? C.acc : C.bad} />
            <span style={{ width: 96, color: C.inkHi }}>{n.name}</span>
            <span style={{ width: 96 }}>
              <Chip color={n.role === 'gateway' ? C.violet : C.info}>{n.role}</Chip>
            </span>
            <span style={{ width: 96, color: C.inkLo }}>{n.ip}</span>
            <span style={{ width: 60, textAlign: 'right', color: C.inkLo }}>{n.rtt}</span>
            <span style={{ width: 56, textAlign: 'right', color: n.jobs ? C.acc : C.inkFaint }}>{n.jobs}</span>
            <span style={{ width: 70, textAlign: 'right', color: C.inkLo }}>{n.done.toLocaleString('en-US')}</span>
            <span style={{ flex: 1, textAlign: 'right', color: n.up ? C.inkDim : C.bad }}>{n.seen}</span>
          </Row>
        ))}
        <div style={{ marginTop: 10, fontSize: 9.5, color: C.inkDim, lineHeight: 1.8 }}>
          a dead node is never a broken path: downloads fall back to arq:queue:dl:master, heavy ops
          stay on the master queue, and links revert to public_base.
        </div>
      </Section>

      <div className="mx-duo" style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 18 }}>
        <Section label="ADD NODE" sigil="✚" right="one-time token · 30 min" pad="22px 14px 12px">
          <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <Input placeholder="name (e.g. dl-ams)" style={{ width: 170 }} />
            <Select defaultValue="download" style={{ width: 140 }}>
              <option value="download">download</option>
              <option value="processing">processing</option>
              <option value="gateway">gateway</option>
            </Select>
            <Btn solid>ISSUE</Btn>
          </div>
          <div style={{ fontSize: 10, color: C.inkDim, marginBottom: 7, letterSpacing: '.06em' }}>
            run this on the new host, as root:
          </div>
          <Cmd>{`curl -fsSL https://panel.example/node/install.sh \\
  | sudo bash -s -- --token 8f3c…a91b`}</Cmd>
          <div style={{ marginTop: 9, fontSize: 9.5, color: C.warn, lineHeight: 1.8 }}>
            shown once — the token is consumed on join (redis GETDEL) and cannot be re-displayed.
          </div>
        </Section>

        <Section label="WG MESH" sigil="⌸" right="10.51.0.1 · master" pad="22px 14px 12px">
          <pre style={{ fontFamily: 'inherit', fontSize: 11, lineHeight: 2, color: C.inkLo }}>
            {`master 10.51.0.1 ─┬─ `}
            <span style={{ color: C.acc }}>dl-fra</span>
            {`    10.51.0.2  42ms
                  ├─ `}
            <span style={{ color: C.acc }}>proc-hel</span>
            {`  10.51.0.3  31ms
                  └─ `}
            <span style={{ color: C.bad }}>edge-thr</span>
            {`  10.51.0.4  down`}
          </pre>
          <div
            style={{
              borderTop: `1px solid ${C.edgeHair}`,
              marginTop: 11,
              paddingTop: 10,
              fontSize: 10,
              color: C.inkDim,
              lineHeight: 1.9,
            }}
          >
            rx <span style={{ color: C.acc }}>4.81 GB</span> · tx{' '}
            <span style={{ color: C.acc }}>17.2 GB</span>
            <br />
            last handshake <span style={{ color: C.inkMid }}>00:00:41</span> ago · 3 peers configured
            <br />
            telabzar-wg-sync.timer <span style={{ color: C.acc }}>active</span>
          </div>
        </Section>
      </div>

      <Section
        label="AFTER A CODE CHANGE" sigil="⚠"
        labelColor={C.warn}
        edge={C.auditEdge}
        bg={C.auditBg}
        right="telabzar update is not enough"
        rightColor={C.warn}
        pad="22px 14px 12px"
      >
        <div style={{ fontSize: 10.5, color: C.ink, lineHeight: 1.9, marginBottom: 9 }}>
          a node runs its own separately-built image, so a fix to run_download / run_op / gateway_node
          does not reach it until that image is rebuilt on the node host:
        </div>
        <Cmd>{`cd /opt/telabzar-node/repo && sudo git pull && sudo bash node/update.sh`}</Cmd>
      </Section>
    </Shell>
  )
}
