/**
 * KOSIGN DRM × Notion — Apps Script proxy (v2: page-body aware)
 * ----------------------------------------------------------------------------
 * Why this exists:
 *   The Notion API has no Access-Control-Allow-Origin header, so a browser
 *   fetch() to https://api.notion.com/* is blocked by CORS. Apps Script Web
 *   Apps are server-side (Google's servers, not the user's browser), so we
 *   can call Notion freely and serve a flat JSON shape back to the frontend
 *   with permissive CORS.
 *
 * What it does:
 *   • Receives GET /exec?empId=EMP-048
 *   • Queries the Notion database for the row whose "EMP ID" property equals empId
 *   • Pulls a few card-header fields from database COLUMNS (Nickname / Name / Role / Photo)
 *   • Fetches the employee page's BODY blocks (headings, paragraphs, bullets, files)
 *     and parses three sections out of it: [기본정보] / [기술경력] / [이력서]
 *   • Merges everything into the flat shape that mock_notion_employees.json uses,
 *     so the same fetchNotionEmployeeData() in index.html consumes both proxy
 *     and mock outputs interchangeably.
 *
 * Notion structure this expects (matches the screenshot at /docs/notion-layout.png):
 *   Database columns (required):
 *     • EMP ID    — Text / Title — lookup key, must match employees.emp_id in Supabase
 *   Database columns (optional but recommended for the profile card):
 *     • Nickname  — Text          — '나나'
 *     • Name      — Text          — 'TANG MOUYCHENG'
 *     • Role      — Text          — 'Software Engineer II'
 *     • Photo     — Files & media — profile photo (first file used)
 *   Page body (anywhere in the page, in any order):
 *     • A heading_1/2/3 with text matching /기본정보/  →  followed by paragraphs of the form
 *       "성명 : ...", "성별 : ...", "학력 : ...", "이메일 : ...", "언어 : ...", "자격증 : ..."
 *     • A heading_1/2/3 with text matching /기술경력|경력/  →  followed by bulleted_list_item blocks
 *     • A heading_1/2/3 with text matching /이력서|첨부|resume/  →  followed by file blocks
 *
 * Setup (≈ 7 minutes — full walkthrough at the end of this comment block):
 *   1. Create a Notion integration → copy the secret_xxx token
 *   2. Share your Notion employee database with that integration
 *   3. Copy the 32-char database ID from the database URL
 *   4. Create a new Apps Script project, paste THIS FILE
 *   5. ⚙ Project Settings → Script properties: add NOTION_TOKEN + NOTION_DATABASE_ID
 *   6. Deploy → Web app → Execute-as: Me, Access: Anyone → copy /exec URL
 *   7. In index.html, set NOTION_PROXY_URL to the /exec URL
 */

const PROP_NAMES = {
  empId: 'EMP ID',     // REQUIRED — lookup key
  nick:  'Nickname',   // optional — Korean nickname on the profile card ('나나')
  name:  'Name',       // optional — uppercase Latin name inside parens ('TANG MOUYCHENG')
  role:  'Role',       // optional — job title under the name ('Software Engineer II')
  photo: 'Photo'       // optional — profile photo (files & media)
};

// ─────────────────────────────────────────────────────────────────────────────
// HTTP entry — frontend calls this with ?empId=EMP-048
// ─────────────────────────────────────────────────────────────────────────────
function doGet(e) {
  const empId = (e.parameter && e.parameter.empId) || '';
  if (!empId) return jsonResponse({ employee: null, error: 'empId required' });

  const TOKEN = PropertiesService.getScriptProperties().getProperty('NOTION_TOKEN');
  const DB_ID = PropertiesService.getScriptProperties().getProperty('NOTION_DATABASE_ID');
  if (!TOKEN || !DB_ID) {
    return jsonResponse({ employee: null, error: 'NOTION_TOKEN / NOTION_DATABASE_ID not set in Script Properties' });
  }

  try {
    // Step 1 — query the database to find the page for this empId.
    const page = queryEmployeePage(TOKEN, DB_ID, empId);
    if (!page) return jsonResponse({ employee: null });

    // Step 2 — pull simple card-header fields from database columns.
    const props = page.properties || {};
    const cardFields = {
      nick:     propText(props[PROP_NAMES.nick]),
      name:     propText(props[PROP_NAMES.name]),
      role:     propText(props[PROP_NAMES.role]),
      photoUrl: propFirstFileUrl(props[PROP_NAMES.photo])
    };

    // Step 3 — fetch the page body and parse the three sections out of it.
    const blocks = fetchAllBlocks(TOKEN, page.id);
    const body   = parsePageBlocks(blocks);

    // Step 4 — merge. Column values win for card-header fields; body parsing fills the rest.
    return jsonResponse({
      employee: {
        id:             propText(props[PROP_NAMES.empId]) || empId,
        nick:           cardFields.nick,
        name:           cardFields.name,
        role:           cardFields.role,
        photoUrl:       cardFields.photoUrl || body.photoUrl,
        fullName:       body.fullName,
        gender:         body.gender,
        university:     body.university,
        email:          body.email,
        languages:      body.languages,
        certificates:   body.certificates,
        techExperience: body.techExperience,
        files:          body.files
      }
    });
  } catch (err) {
    return jsonResponse({ employee: null, error: String(err) });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Notion API helpers
// ─────────────────────────────────────────────────────────────────────────────

// Query the DB by EMP ID. Tries `rich_text` filter first, falls back to `title` filter
// (Notion picks one depending on whether EMP ID is your "Name" column or a regular text column).
function queryEmployeePage(TOKEN, DB_ID, empId) {
  const tryFilter = (filterShape) => {
    const res = UrlFetchApp.fetch(
      `https://api.notion.com/v1/databases/${DB_ID}/query`,
      {
        method: 'post',
        contentType: 'application/json',
        muteHttpExceptions: true,
        headers: { Authorization: `Bearer ${TOKEN}`, 'Notion-Version': '2022-06-28' },
        payload: JSON.stringify({ filter: filterShape, page_size: 1 })
      }
    );
    if (res.getResponseCode() !== 200) return null;
    const body = JSON.parse(res.getContentText());
    return (body.results || [])[0] || null;
  };
  return tryFilter({ property: PROP_NAMES.empId, rich_text: { equals: empId } })
      || tryFilter({ property: PROP_NAMES.empId, title:     { equals: empId } });
}

// Page bodies in Notion can have more than 100 blocks (paginated). Walk all pages of children.
function fetchAllBlocks(TOKEN, pageId) {
  let blocks = [], cursor = null;
  do {
    const url = `https://api.notion.com/v1/blocks/${pageId}/children?page_size=100${cursor ? `&start_cursor=${cursor}` : ''}`;
    const res = UrlFetchApp.fetch(url, {
      method: 'get',
      muteHttpExceptions: true,
      headers: { Authorization: `Bearer ${TOKEN}`, 'Notion-Version': '2022-06-28' }
    });
    if (res.getResponseCode() !== 200) break;
    const body = JSON.parse(res.getContentText());
    blocks = blocks.concat(body.results || []);
    cursor = body.has_more ? body.next_cursor : null;
  } while (cursor);
  return blocks;
}

// ─────────────────────────────────────────────────────────────────────────────
// Block parser — walks blocks, tracks which section we're in, accumulates output
// ─────────────────────────────────────────────────────────────────────────────
function parsePageBlocks(blocks) {
  const out = {
    photoUrl: null, fullName: '', gender: '', university: '', email: '',
    languages: [], certificates: [],
    techExperience: [], files: []
  };
  const txt = (richArr) => (richArr || []).map(x => x.plain_text).join('');
  let section = null; // 'basic' | 'tech' | 'resume' | null

  for (const b of blocks) {
    const type = b.type;

    // Section headers — match any heading level on the bracket-tagged sections.
    if (type === 'heading_1' || type === 'heading_2' || type === 'heading_3') {
      const t = txt(b[type].rich_text);
      if      (/기본\s*정보/.test(t))       section = 'basic';
      else if (/기술\s*경력|경력/.test(t)) section = 'tech';
      else if (/이력서|첨부|resume/i.test(t)) section = 'resume';
      else section = null;
      continue;
    }

    // First image block found on the page → fallback profile photo (if no Photo column).
    if (type === 'image' && !out.photoUrl) {
      out.photoUrl = b.image?.external?.url || b.image?.file?.url || null;
    }

    // [기본정보] — paragraphs of the form "label : value"
    if (section === 'basic' && type === 'paragraph') {
      const line = txt(b.paragraph.rich_text).trim();
      if (!line) continue;
      const m = line.match(/^([^:：]+?)\s*[:：]\s*(.+)$/);
      if (!m) continue;
      const label = m[1].trim();
      const value = m[2].trim();
      if      (/성명|이름/.test(label))    out.fullName     = value;
      else if (/성별/.test(label))         out.gender       = value;
      else if (/학력|학교/.test(label))    out.university   = value;
      else if (/이메일|email/i.test(label)) out.email        = value;
      else if (/언어/.test(label))         out.languages    = value.split(/[,，、]/).map(s => s.trim()).filter(Boolean);
      else if (/자격증|자격/.test(label))  out.certificates = value.split(/[,，、]/).map(s => s.trim()).filter(Boolean);
    }

    // [기술경력] — bulleted_list_item / numbered_list_item collected as plain bullets
    if (section === 'tech') {
      if (type === 'bulleted_list_item') {
        const t = txt(b.bulleted_list_item.rich_text).trim();
        if (t) out.techExperience.push(t);
      } else if (type === 'numbered_list_item') {
        const t = txt(b.numbered_list_item.rich_text).trim();
        if (t) out.techExperience.push(t);
      }
    }

    // [이력서] — file or pdf blocks → attachment rows
    if (section === 'resume' && (type === 'file' || type === 'pdf')) {
      const f = b[type];
      const url = f?.external?.url || f?.file?.url || '#';
      const captionText = txt(f?.caption);
      // Notion file blocks don't always carry a usable name field; fall back to the URL's basename.
      const guessedName = captionText
        || (decodeURIComponent((url.split('?')[0] || '').split('/').pop() || '') || '(파일)');
      const ext = (guessedName.split('.').pop() || '').toLowerCase();
      out.files.push({
        name: guessedName,
        url:  url,
        type: ext,
        size: ''   // Notion's API doesn't return file size; leave blank and the UI hides the row.
      });
    }
  }
  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// Notion property → JS-value helpers
// ─────────────────────────────────────────────────────────────────────────────
function propText(p) {
  if (!p) return '';
  if (p.title)     return (p.title[0]?.plain_text) || '';
  if (p.rich_text) return p.rich_text.map(x => x.plain_text).join('');
  if (p.email)     return p.email || '';
  if (p.select)    return p.select?.name || '';
  return '';
}
function propFirstFileUrl(p) {
  const f = (p?.files || [])[0];
  return f ? (f.external?.url || f.file?.url || '') : null;
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
