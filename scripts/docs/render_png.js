// Renders the .drawio schemes of this folder to PNG (docs/method/schemes/) with mxgraph in headless Chromium.
//
//   npm i mxgraph@4.2.2            (in any folder outside the repository; MXCLIENT below points to it)
//   python3 scripts/docs/build_flow.py && python3 scripts/docs/build_scheme.py     # the .drawio files
//   MXCLIENT=/path/node_modules/mxgraph/javascript/mxClient.min.js node scripts/docs/render_png.js
//
// Needs the Node Playwright of the environment (require('playwright')). Each diagram is drawn at its own bounds, with
// HTML labels, and screenshotted at deviceScaleFactor 2.
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const HERE = __dirname;
const OUT = path.join(HERE, '..', '..', 'docs', 'method', 'schemes');
const MXCLIENT = process.env.MXCLIENT;
const NAMES = process.argv.slice(2).length ? process.argv.slice(2)
  : fs.readdirSync(HERE).filter(f => f.endsWith('.drawio')).map(f => f.replace(/\.drawio$/, ''));

(async () => {
  if (!MXCLIENT || !fs.existsSync(MXCLIENT)) throw new Error('set MXCLIENT to mxClient.min.js of mxgraph@4.2.2');
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 1200, height: 800 } });
  await page.setContent('<html><body style="margin:0;background:#fff"><div id="g" style="position:relative;overflow:hidden"></div></body></html>');
  await page.addScriptTag({ content: 'window.mxLoadResources = false; window.mxLoadStylesheets = false; window.mxBasePath = "";' });
  await page.addScriptTag({ path: MXCLIENT });
  for (const name of NAMES) {
    const xml = fs.readFileSync(path.join(HERE, `${name}.drawio`), 'utf8');
    const model = xml.match(/<mxGraphModel[\s\S]*<\/mxGraphModel>/)[0];
    const size = await page.evaluate((model) => {
      const c = document.getElementById('g');
      c.innerHTML = '';
      c.style.width = '10000px'; c.style.height = '10000px';
      const graph = new mxGraph(c);
      graph.setHtmlLabels(true);
      graph.setEnabled(false);
      const doc = mxUtils.parseXml(model);
      new mxCodec(doc).decode(doc.documentElement, graph.getModel());
      const b = graph.getGraphBounds();
      graph.view.setTranslate(-b.x + 10, -b.y + 10);
      const w = Math.ceil(b.width + 20), h = Math.ceil(b.height + 20);
      c.style.width = w + 'px'; c.style.height = h + 'px';
      return { w, h };
    }, model);
    await page.setViewportSize({ width: size.w, height: size.h });
    await page.locator('#g').screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log(`${name}.png ${size.w}x${size.h}`);
  }
  await browser.close();
})();
