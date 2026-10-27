# 8 Claude Skills สำหรับงานตัดต่อ

ติดตั้งตามคู่มือ Colofill (ข้อมูล ณ 21 ต.ค. 2026) แต่ล็อกเวอร์ชัน (commit) ไว้ใน `tools/skills.json` ให้ได้ของเดิมทุกครั้ง

## ติดตั้ง

ดับเบิลคลิก `install_skills.bat` (ต้องมี git) หรือ

```
python tools/install_skills.py list              # ดูรายการ + เวอร์ชัน
python tools/install_skills.py install           # ลงทั้ง 8
python tools/install_skills.py install gsap-skills ffmpeg-skill
python tools/install_skills.py install --user    # ลงเป็นของทุกโปรเจกต์ (~/.claude/skills)
```

- skill ลงที่ `.claude/skills/` (เฉพาะโปรเจกต์นี้) ชุดที่ต้องมีโฟลเดอร์ของตัวเองลงที่ `third_party/` (ทั้งสองโฟลเดอร์ไม่เข้า git)
- ลงเสร็จให้เปิดแชตใหม่ใน Claude Code เพื่อให้โหลด skill
- **ความปลอดภัย:** skill ของคนอื่นสั่งให้ Claude รันคำสั่งในเครื่องได้ เปิดอ่าน `SKILL.md` ก่อน และลองกับสำเนาคลิป ไม่ใช่ไฟล์ต้นฉบับ
- อัปเดต: แก้ `commit` ใน `tools/skills.json` หลังอ่านการเปลี่ยนแปลงแล้ว รันติดตั้งซ้ำ (ของเดิมถูกแทนที่)

## ใช้ตัวไหนเมื่อไหร่

| ขั้น | skill | ใช้ทำ | ตัวอย่างสั่ง |
|---|---|---|---|
| 1 | herk-edit-kit (`third_party/herk-edit-kit`) | ตัดคลิปดิบ ช่วงเงียบ เทคที่พูดผิด | เปิดโฟลเดอร์นั้นใน Claude Code: `Use edit-video to edit my recording at <ไฟล์>. Tighten dead air and show me the proposed mistake cuts.` |
| 2 | ffmpeg-skill | ซับ ครอป 9:16 ปรับเสียง ส่งออก | `ใส่ซับคำต่อคำแบบ TikTok ให้ clip.mp4 จากไฟล์ subs.srt` |
| 3 | remotion-motion-graphics | ไตเติล intro ป้ายชื่อ | `ทำ intro 4 วินาทีบนคลิป clip.mp4 ขนาด 1080x1920` |
| 4 | video-shotcraft | ช็อตแบบหนัง คลิปโปรโมต | `ใช้ช็อต spotlight-hero-card กับคลิป clip.mp4` |
| 5 | text-to-lottie (+ player ที่ `third_party/text-to-lottie`) | สติกเกอร์ ไอคอนขยับ | `ทำ Lottie ไอคอนหัวใจเด้ง พื้นใส 512x512 ยาว 2 วินาที` |
| 6 | Emil Kowalski (animate, ask-sonner, ...) | ป๊อปอัป การ์ด UI | `ใช้ skill animate ทำการ์ดแจ้งเตือน 3 ใบ` |
| 7 | gsap-* | คำเด้งตามจังหวะพูด | `ทำข้อความ 3 คำเด้งที่วินาที 0.6, 1.5, 2.9 ด้วย GSAP timeline` |
| 8 | threejs-* | วัตถุ 3D | `ทำปุ่ม play 3D สีส้มหมุนลอย 600x600 ด้วย three.js` |

## ข้อควรรู้ (จากคู่มือ)

- herk-edit-kit: ตัวถอดเสียงตั้งต้นใช้ ElevenLabs ต้องมี API key ถ้าจะใช้ Whisper ให้ตั้งค่าตาม `docs/TOOLS-AND-API-KEYS.md`; Whisper ให้เวลาคำต่อกัน ช่วงหยุดอาจไม่เห็น ต้องจับช่วงเงียบจากไฟล์เสียงช่วย (ซึ่งตรงกับตัวตรวจ Dead air ของ Vidcut)
- ffmpeg-skill: ซับต้องใช้ ffmpeg ที่มี libass (`doctor` จะบอกว่าขาดอะไร); ภาษาไทยไม่มีเว้นวรรค ให้แบ่งซับเป็นท่อนสั้นๆ
- Remotion / video-shotcraft: ฟรีสำหรับคนเดียวและทีมเล็ก บริษัทใหญ่ต้องซื้อ license (remotion.dev/license)
- Lottie / Emil / GSAP / three.js ให้ผลเป็นโค้ดเว็บหรือ JSON ต้องเรนเดอร์เป็นวิดีโอพื้นใส (หรือใช้ Remotion / HyperFrames) ก่อนวางบนคลิป
- Export จาก player ของ Lottie ได้ zip โปรเจกต์ ไม่ใช่วิดีโอ
