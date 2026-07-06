// AG983 Assignment 2026 — Methodological Choices Logger
// Deploy as: Execute as Me | Anyone can access (no sign-in required)
// Replace SHEET_ID below with your Google Sheets spreadsheet ID before deploying.

const SHEET_ID   = '1O8_P-yJiPXMQ55bRKSUTPDfnlX5mQ8PH35h1iWaCx4s';
const SHEET_NAME = 'choices';

const COLUMNS = [
  'timestamp',
  'student_id',
  'scenario',
  'corpus_section',
  'case_folding',
  'stopword_list',
  'normalisation_method',
  'number_handling',
  'tfidf_weighting',
  'sentiment_model',
  'pos_threshold',
  'neg_threshold',
  'secondary_metric',
  'lda_n_topics',
  'submission_count',
];

function doPost(e) {
  try {
    const data  = JSON.parse(e.postData.contents);
    const sheet = SpreadsheetApp.openById(SHEET_ID).getSheetByName(SHEET_NAME);

    // Write header row if the sheet is empty
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(COLUMNS);
    }

    // Count prior submissions from this student
    const allData    = sheet.getDataRange().getValues();
    const priorCount = allData.filter(
      row => String(row[1]) === String(data.student_id)
    ).length;

    // Build the row in the same order as COLUMNS
    const row = [
      new Date().toISOString(),
      data.student_id        || '',
      data.scenario          || '',
      data.corpus_section    || '',
      data.case_folding      || '',
      data.stopword_list     || '',
      data.normalisation_method || '',
      data.number_handling   || '',
      data.tfidf_weighting   || '',
      data.sentiment_model   || '',
      data.pos_threshold     !== undefined ? data.pos_threshold : '',
      data.neg_threshold     !== undefined ? data.neg_threshold : '',
      data.secondary_metric  || '',
      data.lda_n_topics      !== undefined ? data.lda_n_topics  : '',
      priorCount + 1,
    ];

    sheet.appendRow(row);

    return ContentService
      .createTextOutput(JSON.stringify({ status: 'success', submission: priorCount + 1 }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: 'error', message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
