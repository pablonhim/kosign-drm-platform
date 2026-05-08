#!/usr/bin/env python3
"""
Apply all Supabase migration patches to index.html and save as
index_supabase.html. Safer than retyping 1500+ lines of working code.
"""
import re
from pathlib import Path

SRC = Path("/Users/pablonhim/Desktop/KOSIGN-DRM-Platform/index.html")
DST = Path("/Users/pablonhim/Desktop/KOSIGN-DRM-Platform/index_supabase.html")

src = SRC.read_text(encoding="utf-8")

# ─── Patch 1: add Supabase CDN <script> in <head> ───────────────
CDN_TAG = '<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>\n'
if "@supabase/supabase-js" not in src:
    src = src.replace("<style>", CDN_TAG + "<style>", 1)
    print("✓ Patch 1: added Supabase CDN <script> tag")
else:
    print("• Patch 1: CDN tag already present, skipping")

# ─── Patch 2a: replace `const SK="cosine_hr_v21";` with Supabase init ──
SUPABASE_INIT = '''const SUPABASE_URL = 'https://YOUR-PROJECT.supabase.co';
const SUPABASE_KEY = 'YOUR-ANON-KEY';
const supa = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);  // renamed from 'sb' to avoid collision with sort function
const SK = "unused";

function dbToJs(r) {
  return {
    empId: r.emp_id, nick: r.nick||'', name: r.name||'',
    gender: r.gender||'', join: r.join_date||'',
    grade: r.grade||'', kgrade: r.kgrade||'',
    jikchak: r.jikchak||'', jikmu: r.jikmu||'',
    type: r.employment_type||'', wonka: r.wonka||'',
    workplace: r.workplace||'', bumun: r.bumun||'',
    center: r.center||'', bu: r.bu||'', team: r.team||'',
    localMgr: r.local_mgr||'', director: r.director||'',
    deptHead: r.dept_head||'', status: r.status||'재직',
    note: r.note||'',
    dispatchStart: r.dispatch_start||'', dispatchEnd: r.dispatch_end||'',
    dispatchCity: r.dispatch_city||'', dispatchClient: r.dispatch_client||'',
    dispatchExtendable: !!r.dispatch_extendable,
    statusHistory: []
  };
}

function jsToDb(e) {
  return {
    emp_id: e.empId, nick: e.nick||null, name: e.name||null,
    gender: e.gender||null, join_date: e.join||null,
    grade: e.grade||null, kgrade: e.kgrade||null,
    jikchak: e.jikchak||null, jikmu: e.jikmu||null,
    employment_type: e.type||null, wonka: e.wonka||null,
    workplace: e.workplace||null, bumun: e.bumun||null,
    center: e.center||null, bu: e.bu||null, team: e.team||null,
    local_mgr: e.localMgr||null, director: e.director||null,
    dept_head: e.deptHead||null, status: e.status||'재직',
    note: e.note||null,
    dispatch_start: e.dispatchStart||null, dispatch_end: e.dispatchEnd||null,
    dispatch_city: e.dispatchCity||null, dispatch_client: e.dispatchClient||null,
    dispatch_extendable: !!e.dispatchExtendable
  };
}'''

OLD_SK = 'const SK="cosine_hr_v21";'
if OLD_SK in src:
    src = src.replace(OLD_SK, SUPABASE_INIT, 1)
    print("✓ Patch 2a: replaced `const SK=...` with Supabase init")
else:
    print("✗ Patch 2a: original `const SK=\"cosine_hr_v21\"` not found — already patched?")

# ─── Patch 2b: replace loadEmps() + saveEmps() ─────────────────
OLD_LOADSAVE = '''function loadEmps(){
  const r=localStorage.getItem(SK);
  if(r){emps=JSON.parse(r);return;}
  // First run: use embedded data
  emps=JSON.parse(JSON.stringify(BASE_DATA));
  localStorage.setItem(SK,JSON.stringify(emps));
}
function saveEmps(){localStorage.setItem(SK,JSON.stringify(emps));}'''

NEW_LOADSAVE = '''async function loadEmps() {
  const { data, error } = await supa.from('employees').select('*').order('emp_id');
  if (error) { console.error(error); toast('데이터 로드 실패','err'); emps=[]; return; }
  emps = data.map(dbToJs);
}

async function saveEmps() {
  const { error } = await supa.from('employees')
    .upsert(emps.map(jsToDb), { onConflict: 'emp_id' });
  if (error) { console.error(error); toast('저장 실패','err'); }
}

async function deleteEmpFromDb(empId) {
  if (!empId) return;
  const { error } = await supa.from('employees').delete().eq('emp_id', empId);
  if (error) { console.error(error); toast('삭제 실패','err'); }
}'''

if OLD_LOADSAVE in src:
    src = src.replace(OLD_LOADSAVE, NEW_LOADSAVE, 1)
    print("✓ Patch 2b: replaced loadEmps/saveEmps with async Supabase versions")
else:
    print("✗ Patch 2b: original loadEmps/saveEmps not found — already patched?")

# ─── Patch 3: make boot sequence async ─────────────────────────
# The original line is one giant single-line statement followed by toast(...)
OLD_BOOT_PATTERN = re.compile(
    r'(\s*)const today=new Date\(\);'
    r'.*?'
    r'toast\("✅ "\+CU\.name\+"님 환영합니다 \("\+devEmps\(\)\.filter\(e=>e\.type!=="한국파견"\)\.length\+"명 개발자 인력\)","ok"\);',
    re.DOTALL
)

NEW_BOOT = r'''\1const today=new Date();
\1const pad=n=>String(n).padStart(2,"0");
\1const todayStr=today.getFullYear()+"-"+pad(today.getMonth()+1)+"-"+pad(today.getDate());
\1const rdEl=document.getElementById("refDate");
\1if(rdEl)rdEl.value=todayStr;

\1loadEmps().then(()=>{
\1  updateAll();
\1  setTimeout(()=>setPill("dashboard"), 80);
\1  setTimeout(()=>{
\1    const d30=emps.filter(e=>e.type==="파견"&&(()=>{const d=calcDday(e.dispatchEnd);return d!==null&&d<=30;})());
\1    if(d30.length){
\1      const al=document.getElementById("dash-alert");
\1      if(al){
\1        al.style.display="flex";
\1        document.getElementById("dash-alert-txt").textContent=`파견 계약 만료 30일 이내: ${d30.map(e=>e.nick||e.name).join(" · ")} — ${d30.length}명`;
\1      }
\1    }
\1  },100);
\1  toast("✅ "+CU.name+"님 환영합니다 ("+devEmps().filter(e=>e.type!=="한국파견").length+"명 개발자 인력)","ok");
\1});'''

new_src, n = OLD_BOOT_PATTERN.subn(NEW_BOOT, src, count=1)
if n:
    src = new_src
    print("✓ Patch 3: made boot sequence async")
else:
    print("✗ Patch 3: boot sequence pattern not found — already patched?")

# ─── Patch 4a: first delete site (around line 1214) ────────────
OLD_DEL_1 = '  emps.splice(idx,1);saveEmps();uc();pf();rl();toast("삭제되었습니다");'
NEW_DEL_1 = '  const removed=emps[idx];emps.splice(idx,1);deleteEmpFromDb(removed?.empId);uc();pf();rl();toast("삭제되었습니다");'
if OLD_DEL_1 in src:
    src = src.replace(OLD_DEL_1, NEW_DEL_1, 1)
    print("✓ Patch 4a: first delete site updated")
else:
    print("✗ Patch 4a: first delete site not found")

# ─── Patch 4b: second delete site (around line 1718) ───────────
OLD_DEL_2 = '  emps.splice(idx,1);saveEmps();uc();pf();\n'
NEW_DEL_2 = '  const removed=emps[idx];emps.splice(idx,1);deleteEmpFromDb(removed?.empId);uc();pf();\n'
if OLD_DEL_2 in src:
    src = src.replace(OLD_DEL_2, NEW_DEL_2, 1)
    print("✓ Patch 4b: second delete site updated")
else:
    print("✗ Patch 4b: second delete site not found")

DST.write_text(src, encoding="utf-8")
print(f"\n✅ Wrote patched file: {DST}")
print(f"   Original kept untouched: {SRC}")
