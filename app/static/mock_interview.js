/* Voice and text mock-interview experience. Audio is never uploaded to Swaya. */
var mockInterviewCatalogData = [];
var mockInterviewAttemptState = null;

window.mockInterview = async function() {
  pushPage(window.mockInterview);
  shell('<div class="nav-row">' + backButton() + '</div><h1>Voice mock interview</h1><p class="muted">Choose a course and lesson. You will answer five role-style questions and get a lesson-specific improvement report.</p><div class="card"><p>Questions are original practice prompts based on the selected module and linked technical references. Scoring checks a published rubric; it is not an AI hiring decision.</p><p class="muted">If you use the microphone, your browser transcribes your speech. Swaya receives and stores only the transcript you submit with the feedback report, not an audio recording.</p><div id="miSetupStatus">Loading your modules…</div></div>');
  try {
    var values = await Promise.all([api('/mock-interviews/catalog'), api('/mock-interviews/history')]);
    mockInterviewCatalogData = values[0] || [];
    window.mockInterviewRenderSetup(mockInterviewCatalogData, values[1] || []);
  } catch (e) {
    shell('<div class="nav-row">' + backButton() + '</div><h1>Voice mock interview</h1><div class="card"><p class="error">' + esc(e.message) + '</p></div>');
  }
};

window.mockInterviewRenderSetup = function(catalog, history) {
  if (!catalog.length) {
    shell('<div class="nav-row">' + backButton() + '</div><h1>Voice mock interview</h1><div class="card"><p>No enrolled course modules are available yet. Enroll in a published course to start an interview.</p></div>');
    return;
  }
  var courseOptions = catalog.map(function(c) {
    return '<option value="' + c.id + '">' + esc(c.title) + '</option>';
  }).join('');
  var historyMarkup = history.length ? history.map(function(item) {
    var score = item.score == null ? 'Not submitted' : Math.round(item.score) + '%';
    return '<button class="secondary mi-history-item" onclick="mockInterviewViewReport(' + item.id + ')"><strong>' + esc(item.course_title) + '</strong><br>' + esc(item.module_title) + '<br><span class="muted">' + esc(new Date(item.created_at).toLocaleString()) + ' · ' + esc(score) + '</span></button>';
  }).join('') : '<p class="muted">Your submitted interview reports will appear here.</p>';
  shell('<div class="nav-row">' + backButton() + '</div><div class="mi-layout"><section><h1>Voice mock interview</h1><p class="muted">Questions are selected from the module you choose. Speak your response or type it in the answer box.</p><div class="card"><label for="miCourse">Course</label><select id="miCourse" onchange="mockInterviewCourseChanged()">' + courseOptions + '</select><label for="miModule">Module</label><select id="miModule"></select><button onclick="mockInterviewStart()" style="margin-top:12px">Start 5-question interview</button></div><div class="card"><h2>How feedback works</h2><p>Each answer is compared with a visible concept checklist. Your report highlights covered points, missing points, and a model answer for review.</p><p class="muted">Voice is optional. You can use speech-to-text when your browser supports it, or type every answer.</p></div></section><aside><div class="card"><h2>Recent reports</h2><div class="mi-history">' + historyMarkup + '</div></div></aside></div>');
  window.mockInterviewCourseChanged();
};

window.mockInterviewCourseChanged = function() {
  var select = document.getElementById('miCourse');
  var moduleSelect = document.getElementById('miModule');
  if (!select || !moduleSelect) return;
  var course = mockInterviewCatalogData.find(function(item) { return String(item.id) === select.value; });
  moduleSelect.innerHTML = (course ? course.modules : []).map(function(item) {
    return '<option value="' + item.id + '">Module ' + item.day_number + ' · ' + esc(item.title) + '</option>';
  }).join('');
};

window.mockInterviewStart = async function() {
  var course = document.getElementById('miCourse');
  var module = document.getElementById('miModule');
  if (!course || !module || !module.value) return;
  try {
    var result = await api('/mock-interviews/start', {
      method: 'POST',
      body: JSON.stringify({course_id: Number(course.value), lesson_id: Number(module.value)})
    });
    mockInterviewAttemptState = {
      id: result.id,
      courseTitle: result.course_title,
      moduleTitle: result.module_title,
      questions: result.questions || [],
      answers: (result.questions || []).map(function() { return ''; }),
      index: 0,
      recognition: null,
      listening: false,
      voiceBase: '',
      voiceFinal: ''
    };
    window.mockInterviewRenderQuestion();
  } catch (e) {
    alert(e.message);
  }
};

window.mockInterviewRenderQuestion = function() {
  var state = mockInterviewAttemptState;
  if (!state) return;
  var q = state.questions[state.index];
  var recognitionSupported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  var readSupported = !!window.speechSynthesis;
  var progress = 'Question ' + (state.index + 1) + ' of ' + state.questions.length;
  var source = q.source_url ? '<a href="' + esc(q.source_url) + '" target="_blank" rel="noopener noreferrer">' + esc(q.source_title || 'Technical reference') + '</a>' : esc(q.source_title || '');
  shell('<div class="nav-row"><button class="secondary" onclick="mockInterview()">Exit interview</button></div><div class="mi-interview"><div class="mi-progress"><span class="pill">' + esc(progress) + '</span><span class="muted">' + esc(state.courseTitle) + ' · ' + esc(state.moduleTitle) + '</span></div><article class="card mi-question-card"><div class="mi-question-meta">' + esc(q.topic) + ' · ' + esc(q.difficulty) + '</div><h1>' + esc(q.prompt) + '</h1><p class="muted">Reference: ' + source + '</p>' + (readSupported ? '<button class="secondary" onclick="mockInterviewReadQuestion()">🔊 Read question aloud</button>' : '') + '<label for="miAnswer">Your answer</label><textarea id="miAnswer" rows="7" maxlength="4000" placeholder="Explain your approach and reasoning…">' + esc(state.answers[state.index] || '') + '</textarea><div class="mi-voice-row">' + (recognitionSupported ? '<button id="miVoiceButton" class="secondary" onclick="mockInterviewToggleVoice()">' + (state.listening ? 'Stop speaking' : '🎙️ Answer by voice') + '</button>' : '<span class="muted">Speech input is unavailable in this browser; typing still works.</span>') + '<span id="miVoiceStatus" class="muted" aria-live="polite"></span></div><div class="mi-controls">' + (state.index > 0 ? '<button class="secondary" onclick="mockInterviewPrevious()">Previous</button>' : '<span></span>') + '<button onclick="mockInterviewNext()">' + (state.index === state.questions.length - 1 ? 'Submit interview' : 'Next question') + '</button></div></article><p class="muted">You may skip a question. The report will mark concepts it could not find in your submitted answer.</p></div>');
};

window.mockInterviewReadQuestion = function() {
  var state = mockInterviewAttemptState;
  if (!state || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(state.questions[state.index].prompt));
};

window.mockInterviewToggleVoice = function() {
  var state = mockInterviewAttemptState;
  if (!state) return;
  if (state.listening && state.recognition) {
    state.recognition.stop();
    return;
  }
  var Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return;
  var box = document.getElementById('miAnswer');
  if (!box) return;
  var recognition = new Recognition();
  recognition.lang = navigator.language || 'en-US';
  recognition.continuous = true;
  recognition.interimResults = true;
  state.voiceBase = box.value ? box.value + ' ' : '';
  state.voiceFinal = '';
  state.recognition = recognition;
  recognition.onstart = function() {
    state.listening = true;
    var button = document.getElementById('miVoiceButton');
    var status = document.getElementById('miVoiceStatus');
    if (button) button.textContent = 'Stop speaking';
    if (status) status.textContent = 'Listening…';
  };
  recognition.onresult = function(event) {
    var interim = '';
    for (var i = event.resultIndex; i < event.results.length; i++) {
      var phrase = event.results[i][0].transcript;
      if (event.results[i].isFinal) state.voiceFinal += phrase + ' ';
      else interim += phrase;
    }
    var answerBox = document.getElementById('miAnswer');
    if (answerBox) answerBox.value = state.voiceBase + state.voiceFinal + interim;
  };
  recognition.onerror = function(event) {
    var status = document.getElementById('miVoiceStatus');
    if (status) status.textContent = event.error === 'not-allowed' ? 'Microphone permission was denied. You can type instead.' : 'Speech input stopped: ' + event.error;
  };
  recognition.onend = function() {
    state.listening = false;
    var button = document.getElementById('miVoiceButton');
    var status = document.getElementById('miVoiceStatus');
    if (button) button.textContent = '🎙️ Answer by voice';
    if (status && status.textContent === 'Listening…') status.textContent = 'Transcription ready.';
  };
  try {
    recognition.start();
  } catch (e) {
    var status = document.getElementById('miVoiceStatus');
    if (status) status.textContent = 'Could not start speech input. Type your answer instead.';
  }
};

window.mockInterviewSaveCurrentAnswer = function() {
  var state = mockInterviewAttemptState;
  if (!state) return;
  var box = document.getElementById('miAnswer');
  if (box) state.answers[state.index] = box.value.trim();
  if (state.recognition && state.listening) state.recognition.stop();
  if (window.speechSynthesis) window.speechSynthesis.cancel();
};

window.mockInterviewPrevious = function() {
  window.mockInterviewSaveCurrentAnswer();
  if (mockInterviewAttemptState && mockInterviewAttemptState.index > 0) {
    mockInterviewAttemptState.index--;
    window.mockInterviewRenderQuestion();
  }
};

window.mockInterviewNext = async function() {
  var state = mockInterviewAttemptState;
  if (!state) return;
  window.mockInterviewSaveCurrentAnswer();
  if (state.index < state.questions.length - 1) {
    state.index++;
    window.mockInterviewRenderQuestion();
    return;
  }
  var answers = state.questions.map(function(question, index) {
    return {question_id: question.id, answer: state.answers[index] || ''};
  });
  try {
    var report = await api('/mock-interviews/' + state.id + '/submit', {
      method: 'POST',
      body: JSON.stringify({answers: answers})
    });
    report.course_title = state.courseTitle;
    report.module_title = state.moduleTitle;
    mockInterviewAttemptState = null;
    window.mockInterviewRenderReport(report);
  } catch (e) {
    alert(e.message);
  }
};

window.mockInterviewRenderReport = function(report) {
  var questions = report.questions || [];
  var items = questions.map(function(item, index) {
    var covered = item.covered_points.length ? '<ul>' + item.covered_points.map(function(point) { return '<li>' + esc(point) + '</li>'; }).join('') + '</ul>' : '<p class="muted">No checklist points were detected yet.</p>';
    var missing = item.improvement_points.length ? '<ul>' + item.improvement_points.map(function(point) { return '<li>' + esc(point) + '</li>'; }).join('') + '</ul>' : '<p class="success">You covered the listed points.</p>';
    var source = item.source_url ? '<a href="' + esc(item.source_url) + '" target="_blank" rel="noopener noreferrer">' + esc(item.source_title || 'Technical reference') + '</a>' : esc(item.source_title || '');
    return '<details class="card mi-report-question"' + (index === 0 ? ' open' : '') + '><summary><strong>Question ' + (index + 1) + ' · ' + esc(item.topic) + '</strong><span class="pill">' + Math.round(item.score) + '% rubric coverage</span></summary><h3>' + esc(item.prompt) + '</h3><p><strong>Your submitted answer</strong></p><p class="mi-answer-copy">' + esc(item.answer || 'Skipped') + '</p><div class="grid"><div><strong>Covered points</strong>' + covered + '</div><div><strong>Scope to improve</strong>' + missing + '</div></div><h4>Model answer</h4><p>' + esc(item.model_answer) + '</p><p class="muted">Reference: ' + source + '</p></details>';
  }).join('');
  var strengths = report.strengths && report.strengths.length ? '<ul>' + report.strengths.map(function(item) { return '<li>' + esc(item) + '</li>'; }).join('') + '</ul>' : '<p>Keep practicing structured answers with evidence and a clear next step.</p>';
  var improvements = report.improvements && report.improvements.length ? '<ul>' + report.improvements.map(function(item) { return '<li>' + esc(item) + '</li>'; }).join('') + '</ul>' : '<p>No repeated gaps were detected by this rubric.</p>';
  shell('<div class="nav-row"><button class="secondary" onclick="mockInterview()">Back to mock interviews</button></div><h1>Your interview feedback</h1><div class="mi-report-head"><div class="card mi-score-card"><span class="muted">Rubric coverage</span><div class="mi-score">' + Math.round(report.score || 0) + '%</div><p>' + esc(report.summary || '') + '</p></div><div class="card"><h2>' + esc(report.module_title || 'Selected module') + '</h2><p>' + esc(report.course_title || '') + '</p><p class="muted">' + esc(report.created_at ? new Date(report.created_at).toLocaleString() : '') + '</p></div></div><div class="grid"><div class="card"><h2>Strengths</h2>' + strengths + '</div><div class="card"><h2>Improvement scope</h2>' + improvements + '</div></div><div class="card"><h2>Answer-by-answer review</h2><p class="muted">' + esc(report.scoring_note || '') + '</p>' + items + '</div>');
};

window.mockInterviewViewReport = async function(id) {
  try {
    var report = await api('/mock-interviews/' + id);
    window.mockInterviewRenderReport(report);
  } catch (e) {
    alert(e.message);
  }
};
