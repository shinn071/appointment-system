const navigation = {
  Student: [['dashboard', '▦', 'Dashboard'], ['book', '+', 'Book Appointment'], ['schedules', '▤', 'Clinic Schedules'], ['appointments', '▣', 'My Appointments'], ['history', '◷', 'Appointment History'], ['notifications', '♧', 'Notifications'], ['profile', '○', 'My Profile']],
  Faculty: [['dashboard', '▦', 'Dashboard'], ['book', '+', 'Book Appointment'], ['schedules', '▤', 'Clinic Schedules'], ['appointments', '▣', 'My Appointments'], ['history', '◷', 'Appointment History'], ['notifications', '♧', 'Notifications'], ['profile', '○', 'My Profile']],
  'Clinic Staff': [['dashboard', '▦', 'Dashboard'], ['schedules', '▤', 'Clinic Schedules'], ['pending', '◷', 'Pending Appointments'], ['records', '▣', 'Appointment Records'], ['notifications', '♧', 'Notifications']],
  'Clinic Personnel': [['dashboard', '▦', 'Dashboard'], ['checkins', '✓', 'Check-in Management'], ['patients', '◉', "Today's Patients"], ['visits', '▤', 'Visit Management'], ['notifications', '♧', 'Notifications']],
  Administrator: [['dashboard', '▦', 'Dashboard'], ['users', '♙', 'User Management'], ['roles', '◉', 'Role Management'], ['settings', '⚙', 'System Settings'], ['notifications', '♧', 'Notifications']]
};

const titles = {
  dashboard: 'Dashboard', book: 'Book Appointment', schedules: 'Clinic Schedules', appointments: 'My Appointments',
  history: 'Appointment History', notifications: 'Notifications', profile: 'My Profile',
  pending: 'Pending Appointments', records: 'Appointment Records', checkins: 'Check-in Management',
  patients: "Today's Patients", visits: 'Visit Management', users: 'User Management',
  roles: 'Role Management', settings: 'System Settings'
};

const clinicServices = [
  'General Consultation',
  'Basic Health Screening',
  'Dental Cleaning',
  'Tooth Extraction (bunot)',
  'Medical Certificate / Health Assessment Request',
  'Dental Consultation and Checkup'
];

let user = null;
let csrfToken = '';
let appointments = [];
let schedules = [];
let dashboardCounts = {};
let directory = [];
let page = 'dashboard';
let toastTimer;

async function api(path, options = {}) {
  const headers = { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) };
  if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = csrfToken;
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers });
  if (response.status === 404) {
    throw new Error('Clinic backend is not connected to this Firebase Hosting site (404).');
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(`Server returned an invalid response (${response.status}).`);
  }
  if (!response.ok) {
    if (response.status === 401 && page !== 'login') showLogin();
    throw new Error(data.error || `Request failed (${response.status}).`);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function formatDate(value, options = { month: 'short', day: 'numeric', year: 'numeric' }) {
  if (!value) return '—';
  const date = new Date(`${value.slice(0, 10)}T12:00:00`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('en', options).format(date);
}

function formatTime(value) {
  if (!value) return '';
  const [hour, minute] = value.split(':').map(Number);
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour >= 12 ? 'PM' : 'AM'}`;
}

function localDateString(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function isFutureAppointment(item, now = new Date()) {
  const today = localDateString(now);
  const currentTime = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  return item.date > today || (item.date === today && item.start > currentTime);
}

function badge(status) {
  return `<span class="status-badge status-${escapeHtml(status.toLowerCase().replace(/\s+/g, '-'))}">${escapeHtml(status)}</span>`;
}

function showToast(message, error = false) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.style.background = error ? '#b91c1c' : '';
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 3200);
}

function fullNameInitials(name) {
  return (name || '').trim().split(/\s+/).slice(0, 2).map(part => part[0] || '').join('').toUpperCase();
}

async function loadData() {
  const requests = [api('/api/appointments'), api('/api/dashboard')];
  if (navigation[user.role].some(item => item[0] === 'schedules')) requests.push(api('/api/schedules'));
  if (user.role === 'Administrator' && ['users', 'roles'].includes(page)) requests.push(api('/api/users'));
  const results = await Promise.all(requests);
  appointments = results[0].appointments;
  dashboardCounts = results[1].counts;
  schedules = requests.length >= 3 && results[2]?.schedules ? results[2].schedules : [];
  directory = user.role === 'Administrator' && ['users', 'roles'].includes(page) ? results.at(-1).users : [];
}

function updateHeader() {
  document.getElementById('user-name').textContent = user.name;
  document.getElementById('user-avatar').textContent = fullNameInitials(user.name);
  document.getElementById('user-role').textContent = user.role;
  document.getElementById('profile-summary').textContent = `${user.name} · ${user.role} · ${user.email}`;
}

function renderNavigation() {
  document.getElementById('sidebar-nav').innerHTML = navigation[user.role].map(([id, icon, label]) =>
    `<button class="nav-link${page === id ? ' active' : ''}" data-page="${id}"><span class="nav-icon" aria-hidden="true">${icon}</span><span>${label}</span></button>`
  ).join('');
}

function statCard(title, value, caption, icon) {
  return `<article class="stat-card"><div class="stat-top"><span>${title}</span><span class="stat-icon" aria-hidden="true">${icon}</span></div><div class="stat-value">${value}</div><div class="stat-caption">${caption}</div></article>`;
}

function getStats() {
  const c = dashboardCounts;
  if (user.role === 'Administrator') return [
    ['Total Users', c.totalUsers, 'Registered campus accounts', '♙'],
    ['Active Accounts', c.activeUsers, 'Accounts enabled for sign in', '✓'],
    ['Inactive Accounts', c.inactiveUsers, 'Accounts currently disabled', '○'],
    ['Appointment Requests', c.appointmentRequests, 'All recorded clinic requests', '▣']
  ];
  if (user.role === 'Clinic Staff') return [
    ["Today's Appointments", c.today, 'Scheduled for today', '▣'],
    ['Pending Requests', c.pending, 'Awaiting review', '◷'],
    ['Approved Appointments', c.approved, 'Confirmed requests', '✓'],
    ['Available Schedules', c.availableSchedules, 'Schedules with open slots', '▤']
  ];
  if (user.role === 'Clinic Personnel') return [
    ["Today's Check-ins", c.checkedIn, 'Patients checked in today', '✓'],
    ['Waiting Patients', c.waiting, 'Approved appointments today', '◷'],
    ['Visits in Progress', c.checkedIn, 'Patients checked into the clinic', '◉'],
    ['Completed Visits', c.completed, 'Recorded as completed', '▣']
  ];
  return [
    ['Upcoming Appointments', c.upcoming, 'Your future clinic visits', '▣'],
    ['Pending Requests', c.pending, 'Awaiting clinic review', '◷'],
    ['Approved Appointments', c.approved, 'Confirmed clinic visits', '✓'],
    ['Completed Visits', c.completed, 'Past visits completed', '♡']
  ];
}

function renderAppointmentTable(rows, options = {}) {
  if (!rows.length) return `<div class="empty-state compact"><span class="empty-state-icon">▣</span><strong>${options.title || 'No appointments yet'}</strong><p>${options.message || 'Appointment records will appear here when available.'}</p></div>`;
  const staff = ['Clinic Staff', 'Clinic Personnel', 'Administrator'].includes(user.role);
  return `<div class="table-wrap"><table class="data-table"><thead><tr>${staff ? '<th>PATIENT</th>' : ''}<th>APPOINTMENT NO.</th><th>CLINIC SERVICE</th><th>DATE &amp; TIME</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>${rows.map(item => {
    const patientActions = item.status === 'Pending' && user.role === 'Clinic Staff'
      ? `<button class="text-link" data-review="${item.dbId}" data-action="approve">Approve</button> <button class="text-link danger-link" data-review="${item.dbId}" data-action="reject">Reject</button>`
      : item.status === 'Approved' && user.role === 'Clinic Personnel'
        ? `<button class="text-link" data-review="${item.dbId}" data-action="check-in">Check in</button>`
        : item.status === 'Checked-In' && user.role === 'Clinic Personnel'
          ? `<button class="text-link" data-review="${item.dbId}" data-action="complete">Complete visit</button>`
          : `<button class="text-link" data-view="${item.id}">View details</button>`;
    return `<tr>${staff ? `<td>${escapeHtml(item.patientName || '')}<br><span class="muted">${escapeHtml(item.patientEmail || '')}</span></td>` : ''}<td><strong>${escapeHtml(item.id)}</strong></td><td>${escapeHtml(item.service)}</td><td>${formatDate(item.date)}<br><span class="muted">${formatTime(item.start)}</span></td><td>${badge(item.status)}</td><td>${patientActions}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function scheduleCard(item, showService = true) {
  const full = item.remaining <= 0;
  const limited = item.remaining <= 2 && !full;
  const status = full ? 'Full' : limited ? 'Limited availability' : 'Available';
  const statusClass = full ? 'status-cancelled' : limited ? 'status-pending' : 'status-completed';
  return `<article class="schedule-card">${showService ? `<div class="schedule-card-top"><h3>${escapeHtml(item.service)}</h3><span class="status-badge ${statusClass}">${status}</span></div>` : `<div class="schedule-card-top"><p>${formatDate(item.date, { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' })}</p><span class="status-badge ${statusClass}">${status}</span></div>`}<div class="schedule-meta"><span>◷ &nbsp;${formatTime(item.start)} – ${formatTime(item.end)}</span><span>▣ &nbsp;${item.remaining} of ${item.capacity} slots left</span></div><button class="button ${full ? 'button-secondary' : 'button-primary'}" data-book-schedule="${item.id}" ${full ? 'disabled' : ''}>${full ? 'No slots available' : 'Book appointment'}</button>${['Clinic Staff', 'Administrator'].includes(user.role) ? `<button class="text-link" data-edit-schedule="${item.id}">Edit schedule</button>` : ''}</article>`;
}

function renderDashboard() {
  const isPatient = ['Student', 'Faculty'].includes(user.role);
  const greeting = new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening';
  const upcoming = appointments.filter(item => ['Pending', 'Approved'].includes(item.status) && isFutureAppointment(item)).sort((a, b) => a.date.localeCompare(b.date) || a.start.localeCompare(b.start))[0];
  const open = schedules.filter(item => item.remaining > 0).slice(0, 3);
  const welcomeAction = isPatient ? 'book' : user.role === 'Clinic Staff' ? 'pending' : user.role === 'Clinic Personnel' ? 'checkins' : 'users';
  const main = isPatient ? `
    <section class="content-grid"><article class="panel"><div class="panel-heading"><div><h3>Upcoming appointment</h3><p>Your next campus clinic visit</p></div><button class="text-link" data-page="appointments">View all</button></div>${upcoming ? `<div class="appointment-highlight"><div class="date-tile"><strong>${formatDate(upcoming.date, { day: 'numeric' })}</strong><span>${formatDate(upcoming.date, { month: 'short' })}</span></div><div class="appointment-highlight-copy"><strong>${escapeHtml(upcoming.service)}</strong><p>${formatDate(upcoming.date)} · ${formatTime(upcoming.start)}</p>${badge(upcoming.status)}</div></div>` : `<div class="empty-state"><span class="empty-state-icon">♡</span><strong>No upcoming appointments</strong><p>Your next appointment will appear here after you book a visit.</p></div>`}</article>
    <article class="panel"><div class="panel-heading"><div><h3>Next available schedules</h3><p>Find a time that works for you</p></div><button class="text-link" data-page="schedules">See all</button></div><div class="schedule-list">${open.map(item => `<div class="schedule-row"><div><strong>${escapeHtml(item.service)}</strong><small>${formatDate(item.date, { weekday: 'short', month: 'short', day: 'numeric' })} · ${formatTime(item.start)}</small></div><div class="schedule-availability"><span>${item.remaining} slots</span><button data-book-schedule="${item.id}">Book →</button></div></div>`).join('')}</div></article></section>
    <section class="panel section-panel"><div class="panel-heading"><div><h3>Recent appointments</h3><p>Your latest clinic requests</p></div><button class="text-link" data-page="history">View history</button></div>${renderAppointmentTable(appointments.slice(0, 4))}</section>` :
    user.role === 'Administrator' ? `<section class="content-grid"><article class="panel"><div class="panel-heading"><div><h3>Account management</h3><p>Manage user accounts and assign authorized roles.</p></div><button class="text-link" data-page="users">Manage users →</button></div><div class="empty-state"><span class="empty-state-icon">♙</span><strong>Role assignments stay under your control</strong><p>Only administrators can assign clinic roles or deactivate accounts.</p></div></article><article class="panel"><div class="panel-heading"><div><h3>System shortcuts</h3><p>Manage clinic access and settings</p></div></div><div class="schedule-list"><div class="schedule-row"><strong>Role management</strong><button class="text-link" data-page="roles">Open →</button></div><div class="schedule-row"><strong>System settings</strong><button class="text-link" data-page="settings">Open →</button></div></div></article></section>` :
      `<section class="panel section-panel"><div class="panel-heading"><div><h3>${user.role === 'Clinic Staff' ? 'Pending appointment requests' : "Today's patient queue"}</h3><p>Patient records are available only to authorized clinic roles.</p></div><button class="text-link" data-page="${user.role === 'Clinic Staff' ? 'pending' : 'patients'}">Open queue →</button></div>${renderAppointmentTable(user.role === 'Clinic Staff' ? appointments.filter(item => item.status === 'Pending') : appointments)}</section>`;
  return `<section class="welcome-card"><div class="welcome-copy"><span class="eyebrow">CAMPUS CLINIC WORKSPACE</span><h2>Good ${greeting}, ${escapeHtml(user.name.split(' ')[0])}.</h2><p>${isPatient ? 'Manage appointments and find the care you need, right on campus.' : 'Here is an overview of campus clinic activity.'}</p></div><button class="welcome-action" data-page="${welcomeAction}">${isPatient ? '＋ &nbsp; Book an appointment' : 'Open workspace &nbsp; →'}</button></section><section class="stat-grid" aria-label="Appointment summary">${getStats().map(item => statCard(...item)).join('')}</section>${main}`;
}

function renderSchedules() {
  const staffControls = ['Clinic Staff', 'Administrator'].includes(user.role)
    ? `<button class="button button-primary" id="create-schedule-button">＋ &nbsp; Create schedule</button>` : '';
  return `<div class="page-heading"><div><h2>Clinic Schedules</h2><p>Weekday schedules repeat Monday through Friday. Appointment times and remaining slots are shown up to 90 days ahead.</p></div>${staffControls}</div>${['Clinic Staff', 'Administrator'].includes(user.role) ? '<div id="schedule-editor"></div>' : ''}<section class="panel" style="margin-bottom:15px"><div class="toolbar"><input class="search-input" id="schedule-search" type="search" placeholder="Search services…"><select id="service-filter" aria-label="Filter by clinic service"><option value="">All clinic services</option>${clinicServices.map(s => `<option>${escapeHtml(s)}</option>`).join('')}</select><input id="date-filter" type="date" aria-label="Filter schedules by date"></div></section><section id="schedule-results" class="service-schedule-list">${renderServiceScheduleGroups()}</section>`;
}

function renderServiceScheduleGroups(query = '', serviceFilter = '', dateFilter = '') {
  const matchingServices = clinicServices.filter(service =>
    service.toLowerCase().includes(query) && (!serviceFilter || service === serviceFilter)
  );
  if (!matchingServices.length) return '<div class="panel empty-state"><strong>No matching clinic services</strong><p>Try changing your search or service filter.</p></div>';
  return matchingServices.map(service => {
    const publishedSchedules = schedules.filter(item => item.service === service);
    const visibleSchedules = publishedSchedules.filter(item => !dateFilter || item.date === dateFilter);
    const emptyMessage = publishedSchedules.length ? 'No times match the selected date.' : 'No appointment times posted yet.';
    return `<article class="service-schedule-group"><div class="service-schedule-heading"><h3>${escapeHtml(service)}</h3></div><div class="service-schedule-slots">${visibleSchedules.length ? visibleSchedules.map(item => scheduleCard(item, false)).join('') : `<p class="service-no-slots">${emptyMessage}</p>`}</div></article>`;
  }).join('');
}

function renderBooking() {
  return `<div class="page-heading"><div><h2>Book an appointment</h2><p>Choose a clinic service and request a convenient time.</p></div></div><div id="booking-success"></div><div class="booking-layout"><form id="booking-form" class="panel booking-form"><div class="progress-steps"><span class="step active"><span class="step-number">1</span> Details</span><span class="step-line"></span><span class="step"><span class="step-number">2</span> Review</span><span class="step-line"></span><span class="step"><span class="step-number">3</span> Submit</span></div><h3>Tell us what you need</h3><p class="form-description">Select a service and available date. The clinic will review your request.</p><label for="booking-service">Clinic service</label><select id="booking-service" required><option value="">Select a service</option>${clinicServices.map(s => `<option>${escapeHtml(s)}</option>`).join('')}</select><label for="booking-schedule">Available date and time</label><select id="booking-schedule" required><option value="">Select a service first</option></select><label for="booking-reason">Reason for visit</label><textarea id="booking-reason" required maxlength="500" placeholder="Briefly describe what you'd like help with (up to 500 characters)."></textarea><div class="form-actions"><button class="button button-secondary" type="reset">Clear form</button><button class="button button-primary" type="submit">Submit request →</button></div></form><aside class="panel booking-summary"><div class="panel-heading"><div><h3>Appointment summary</h3><p>Review before sending your request</p></div></div><div class="summary-line"><span>Service</span><strong id="summary-service">Not selected</strong></div><div class="summary-line"><span>Date</span><strong id="summary-date">Not selected</strong></div><div class="summary-line"><span>Time</span><strong id="summary-time">Not selected</strong></div><div class="summary-line"><span>Status</span><strong>${badge('Pending')}</strong></div><div class="summary-note">Your appointment is not confirmed until clinic staff reviews it. For urgent care, contact campus health services directly.</div></aside></div>`;
}

function renderAppointments(history = false) {
  const rows = appointments.filter(item => history
    ? ['Completed', 'Rejected', 'Cancelled'].includes(item.status)
    : !['Completed', 'Rejected', 'Cancelled'].includes(item.status));
  return `<div class="page-heading"><div><h2>${history ? 'Appointment history' : 'My appointments'}</h2><p>${history ? 'Review completed and closed appointment requests.' : 'View and manage your campus clinic requests.'}</p></div>${user.role === 'Student' || user.role === 'Faculty' ? '<button class="button button-primary" data-page="book">＋ &nbsp; Book appointment</button>' : ''}</div><section class="panel section-panel"><div class="panel-heading"><div><h3>${history ? 'Past appointments' : 'Your requests'}</h3><p>Live records from the clinic database</p></div><div class="toolbar"><input id="appointment-search" class="search-input" type="search" placeholder="Search appointments…"><select id="appointment-status-filter"><option value="">All statuses</option>${['Pending', 'Approved', 'Rejected', 'Cancelled', 'Checked-In', 'Completed'].map(s => `<option>${s}</option>`).join('')}</select></div></div><div id="appointment-table">${renderAppointmentTable(rows, { title: history ? 'No appointment history' : 'No appointments yet', message: 'Book a clinic visit to see your appointment here.' })}</div></section>`;
}

function renderDetails(item) {
  return `<div class="page-heading"><div><h2>Appointment details</h2><p>Request ${escapeHtml(item.id)}</p></div><button class="button button-secondary" data-page="appointments">← &nbsp; Back to appointments</button></div><div class="detail-layout"><section class="panel"><div class="panel-heading"><div><h3>${escapeHtml(item.service)}</h3><p>${escapeHtml(item.id)}</p></div>${badge(item.status)}</div><div class="detail-list"><div class="detail-item"><span>Appointment date</span><strong>${formatDate(item.date)}</strong></div><div class="detail-item"><span>Appointment time</span><strong>${formatTime(item.start)} – ${formatTime(item.end)}</strong></div><div class="detail-item"><span>Request submitted</span><strong>${formatDate(item.createdAt)}</strong></div><div class="detail-item"><span>Status</span><strong>${escapeHtml(item.status)}</strong></div><div class="detail-item" style="grid-column:1/-1"><span>Reason for visit</span><strong>${escapeHtml(item.reason)}</strong></div>${item.reviewReason ? `<div class="detail-item" style="grid-column:1/-1"><span>Review information</span><strong>${escapeHtml(item.reviewReason)}</strong></div>` : ''}</div>${item.status === 'Pending' ? '<div class="form-actions"><button class="button button-secondary" data-cancel-appointment="' + item.dbId + '">Cancel request</button></div>' : ''}</section><aside class="panel"><div class="panel-heading"><div><h3>Request timeline</h3><p>Appointment status updates</p></div></div><div class="timeline"><div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-copy"><strong>Request submitted</strong><small>${formatDate(item.createdAt)}</small></div></div>${item.status !== 'Pending' ? `<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-copy"><strong>${escapeHtml(item.status)}</strong><small>${item.reviewReason ? escapeHtml(item.reviewReason) : 'Status updated by the clinic'}</small></div></div>` : ''}</div></aside></div>`;
}

function renderUsers() {
  const roles = ['Student', 'Faculty', 'Clinic Staff', 'Clinic Personnel', 'Administrator'];
  return `<div class="page-heading"><div><h2>User Management</h2><p>Create clinic accounts, assign authorized roles, and manage account access.</p></div></div><form id="admin-create-form" class="panel booking-form admin-create-form"><div class="panel-heading"><div><h3>Create a clinic account</h3><p>For Clinic Staff, Clinic Personnel, or additional Administrators. Share the initial password securely.</p></div></div><div class="admin-form-grid"><div><label for="admin-create-name">Full name</label><input class="field-control" id="admin-create-name" required maxlength="120"></div><div><label for="admin-create-email">School email</label><input class="field-control" id="admin-create-email" type="email" required maxlength="254"></div><div><label for="admin-create-id">School ID or employee ID</label><input class="field-control" id="admin-create-id" required maxlength="64"></div><div><label for="admin-create-role">Account role</label><select class="field-control" id="admin-create-role" required>${roles.map(role => `<option>${role}</option>`).join('')}</select></div><div><label for="admin-create-password">Initial password</label><div class="input-wrap"><input id="admin-create-password" type="password" autocomplete="new-password" minlength="8" maxlength="128" pattern="(?=.*[0-9])(?=.*[^A-Za-z0-9\\s]).{8,}" title="Use 8–128 characters, including a number and a symbol." required><button class="password-toggle" type="button" data-toggle-password="admin-create-password" aria-label="Show password">Show</button></div><p class="password-hint">At least 8 characters, including a number and a symbol.</p></div></div><p id="admin-create-message" class="form-message" aria-live="polite"></p><button class="button button-primary" type="submit">Create account</button></form><section class="panel section-panel"><div class="panel-heading"><div><h3>Registered accounts</h3><p>Role changes take effect immediately. Public registration only creates Student and Faculty accounts.</p></div><div class="toolbar"><input class="search-input" id="user-search" type="search" placeholder="Search accounts…"></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>NAME</th><th>EMAIL</th><th>SCHOOL ID</th><th>ROLE</th><th>ACCOUNT</th><th>ACTION</th></tr></thead><tbody id="users-table-body">${directory.map(item => `<tr data-user-row="${item.id}"><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.email)}</td><td>${escapeHtml(item.schoolId)}</td><td><select class="field-control" data-user-role="${item.id}">${roles.map(role => `<option ${item.role === role ? 'selected' : ''}>${role}</option>`).join('')}</select></td><td><select class="field-control" data-user-active="${item.id}"><option value="true" ${item.active ? 'selected' : ''}>Active</option><option value="false" ${item.active ? '' : 'selected'}>Inactive</option></select></td><td><button class="text-link" data-save-user="${item.id}">Save</button></td></tr>`).join('')}</tbody></table></div>${directory.length ? '' : '<div class="empty-state"><strong>No registered accounts</strong><p>Accounts appear here after users register.</p></div>'}</section>`;
}

function renderPage() {
  if (page === 'dashboard') return renderDashboard();
  if (page === 'schedules') return renderSchedules();
  if (page === 'book') return renderBooking();
  if (page === 'appointments') return renderAppointments();
  if (page === 'history') return renderAppointments(true);
  if (page === 'users') return renderUsers();
  if (page === 'roles') return `<div class="page-heading"><div><h2>Role Management</h2><p>Clinic roles and privileges in this system.</p></div><button class="button button-primary" data-page="users">Manage users →</button></div><section class="schedule-grid">${[['Student','Book and view personal appointments.'],['Faculty','Book and view personal appointments.'],['Clinic Staff','Manage schedules and review appointment requests.'],['Clinic Personnel','Manage today’s check-ins and visit status.'],['Administrator','Manage user accounts, clinic roles, and system access.']].map(([role, description]) => `<article class="schedule-card"><h3>${role}</h3><p>${description}</p></article>`).join('')}</section>`;
  if (page === 'settings') return `<div class="page-heading"><div><h2>System Settings</h2><p>Operational settings require a configured campus deployment.</p></div></div><section class="panel"><h3>Campus clinic</h3><p class="muted">Core authentication and clinic schedules are managed by the application configuration and database.</p></section>`;
  if (page === 'notifications') return `<div class="page-heading"><div><h2>Notifications</h2><p>Updates about campus clinic appointments.</p></div></div><section class="panel">${appointments.length ? `<div class="schedule-list">${appointments.slice(0, 12).map(item => `<div class="schedule-row"><div><strong>Appointment ${escapeHtml(item.status.toLowerCase())}</strong><small>${escapeHtml(item.id)} · ${escapeHtml(item.service)} · ${formatDate(item.date)}</small></div>${badge(item.status)}</div>`).join('')}</div>` : '<div class="empty-state"><strong>No notifications yet</strong><p>Appointment updates will appear here.</p></div>'}</section>`;
  if (page === 'profile') return `<div class="page-heading"><div><h2>My Profile</h2><p>Update your account details.</p></div></div><form id="profile-form" class="panel profile-panel"><div class="panel-heading"><div><h3>Personal information</h3><p>Your account is managed by the campus clinic.</p></div></div><label for="profile-name">Full name</label><input id="profile-name" required value="${escapeHtml(user.name)}"><label for="profile-email">Email</label><input id="profile-email" type="email" required value="${escapeHtml(user.email)}"><p class="muted">Role: ${escapeHtml(user.role)} · Contact an administrator to change account roles.</p><button class="button button-primary" type="submit">Save changes</button></form>`;
  if (page === 'pending' || page === 'records' || page === 'checkins' || page === 'patients' || page === 'visits') {
    const rows = page === 'pending' ? appointments.filter(item => item.status === 'Pending')
      : page === 'checkins' || page === 'patients' ? appointments.filter(item => item.date === localDateString() && ['Approved', 'Checked-In', 'Completed'].includes(item.status))
      : page === 'visits' ? appointments.filter(item => ['Checked-In', 'Completed'].includes(item.status)) : appointments;
    return `<div class="page-heading"><div><h2>${titles[page]}</h2><p>${page === 'pending' ? 'Review requests and record a decision. Rejections require an explanation.' : 'Appointment records available to your assigned clinic role.'}</p></div></div><section class="panel section-panel"><div class="panel-heading"><div><h3>${page === 'pending' ? 'Pending requests' : 'Appointment queue'}</h3><p>Patient records are protected by your assigned account role.</p></div><div class="toolbar"><input id="appointment-search" class="search-input" type="search" placeholder="Search appointments…"><select id="appointment-status-filter"><option value="">All statuses</option>${['Pending', 'Approved', 'Rejected', 'Cancelled', 'Checked-In', 'Completed'].map(s => `<option>${s}</option>`).join('')}</select></div></div><div id="appointment-table">${renderAppointmentTable(rows, { title: 'No appointments to display', message: 'There are no matching records at this time.' })}</div></section>`;
  }
  return '<section class="panel empty-state"><strong>Page not found</strong><p>Select an item from the navigation.</p></section>';
}

async function openPage(nextPage) {
  if (!titles[nextPage] || !navigation[user.role].some(item => item[0] === nextPage)) return;
  page = nextPage;
  document.getElementById('page-title').textContent = titles[page];
  document.getElementById('breadcrumb-current').textContent = titles[page];
  renderNavigation();
  document.getElementById('main-content').innerHTML = '<section class="panel empty-state"><strong>Loading…</strong></section>';
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-scrim').classList.remove('visible');
  try {
    await loadData();
    document.getElementById('main-content').innerHTML = renderPage();
    bindPageEvents();
  } catch (error) {
    document.getElementById('main-content').innerHTML = `<section class="panel empty-state"><strong>Unable to load this page</strong><p>${escapeHtml(error.message)}</p><button class="button button-secondary" data-retry>Try again</button></section>`;
    document.querySelector('[data-retry]')?.addEventListener('click', () => openPage(page));
  }
}

function updateSummary() {
  const service = document.getElementById('booking-service');
  const schedule = document.getElementById('booking-schedule');
  if (!service || !schedule) return;
  const chosen = schedules.find(item => String(item.id) === schedule.value);
  document.getElementById('summary-service').textContent = service.value || 'Not selected';
  document.getElementById('summary-date').textContent = chosen ? formatDate(chosen.date) : 'Not selected';
  document.getElementById('summary-time').textContent = chosen ? `${formatTime(chosen.start)} – ${formatTime(chosen.end)}` : 'Not selected';
}

function bindPageEvents() {
  const main = document.getElementById('main-content');
  bindPasswordToggles(main);
  main.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => openPage(button.dataset.page)));
  bindAppointmentActions();
  bindScheduleActions();
  main.querySelectorAll('[data-cancel-appointment]').forEach(button => button.addEventListener('click', async () => {
    if (!window.confirm('Cancel this pending appointment request?')) return;
    try {
      await api(`/api/appointments/${button.dataset.cancelAppointment}/action`, { method: 'POST', body: JSON.stringify({ action: 'cancel' }) });
      showToast('Appointment request cancelled.');
      openPage('appointments');
    } catch (error) {
      showToast(error.message, true);
    }
  }));
  const adminCreateForm = document.getElementById('admin-create-form');
  if (adminCreateForm) adminCreateForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!adminCreateForm.reportValidity()) return;
    const message = document.getElementById('admin-create-message');
    message.textContent = '';
    try {
      await api('/api/users', { method: 'POST', body: JSON.stringify({
        name: document.getElementById('admin-create-name').value.trim(),
        email: document.getElementById('admin-create-email').value.trim(),
        schoolId: document.getElementById('admin-create-id').value.trim(),
        role: document.getElementById('admin-create-role').value,
        password: document.getElementById('admin-create-password').value
      }) });
      showToast('Account created successfully.');
      await openPage('users');
    } catch (error) {
      message.textContent = error.message;
    }
  });

  const service = document.getElementById('booking-service');
  if (service) {
    const schedule = document.getElementById('booking-schedule');
    service.addEventListener('change', () => fillScheduleOptions());
    schedule.addEventListener('change', updateSummary);
    document.getElementById('booking-form').addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      if (!form.reportValidity()) return;
      try {
        const result = await api('/api/appointments', {
          method: 'POST',
          body: JSON.stringify({ scheduleId: Number(schedule.value), reason: document.getElementById('booking-reason').value.trim() })
        });
        document.getElementById('booking-success').innerHTML = `<div class="success-banner"><strong>Request submitted successfully</strong>Reference number: ${escapeHtml(result.appointment.id)} &nbsp; ${badge('Pending')}</div>`;
        showToast('Appointment request submitted.');
        await loadData();
        const options = document.getElementById('booking-service');
        options.innerHTML = `<option value="">Select a service</option>${clinicServices.map(s => `<option>${escapeHtml(s)}</option>`).join('')}`;
        document.getElementById('booking-schedule').innerHTML = '<option value="">Select a service first</option>';
        document.getElementById('booking-reason').value = '';
        updateSummary();
      } catch (error) {
        showToast(error.message, true);
      }
    });
    document.getElementById('booking-form').addEventListener('reset', () => setTimeout(() => {
      document.getElementById('booking-schedule').innerHTML = '<option value="">Select an available schedule</option>';
      updateSummary();
    }));
  }

  const scheduleSearch = document.getElementById('schedule-search');
  if (scheduleSearch) {
    const update = () => {
      const query = scheduleSearch.value.trim().toLowerCase();
      const serviceFilter = document.getElementById('service-filter').value;
      const dateFilter = document.getElementById('date-filter').value;
      document.getElementById('schedule-results').innerHTML = renderServiceScheduleGroups(query, serviceFilter, dateFilter);
      bindScheduleActions();
    };
    [scheduleSearch, document.getElementById('service-filter'), document.getElementById('date-filter')].forEach(control => {
      control.addEventListener(control.tagName === 'SELECT' || control.type === 'date' ? 'change' : 'input', update);
    });
    bindScheduleActions();
  }

  const search = document.getElementById('appointment-search');
  if (search) {
    const update = () => {
      const query = search.value.trim().toLowerCase();
      const status = document.getElementById('appointment-status-filter').value;
      const filtered = appointments.filter(item => (!status || item.status === status) && [item.id, item.service, item.status, item.date, item.patientName || ''].some(value => value.toLowerCase().includes(query)));
      document.getElementById('appointment-table').innerHTML = renderAppointmentTable(filtered, { title: 'No matching appointments', message: 'Try changing your search or status filter.' });
      bindAppointmentActions();
    };
    search.addEventListener('input', update);
    document.getElementById('appointment-status-filter').addEventListener('change', update);
  }

  const profileForm = document.getElementById('profile-form');
  if (profileForm) profileForm.addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const result = await api('/api/profile', { method: 'PUT', body: JSON.stringify({ name: document.getElementById('profile-name').value.trim(), email: document.getElementById('profile-email').value.trim() }) });
      user = result.user;
      updateHeader();
      showToast('Profile updated.');
    } catch (error) {
      showToast(error.message, true);
    }
  });

  const userSearch = document.getElementById('user-search');
  if (userSearch) userSearch.addEventListener('input', () => {
    const query = userSearch.value.toLowerCase();
    document.querySelectorAll('[data-user-row]').forEach(row => row.classList.toggle('hidden', !row.innerText.toLowerCase().includes(query)));
  });
  main.querySelectorAll('[data-save-user]').forEach(button => button.addEventListener('click', async () => {
    const id = button.dataset.saveUser;
    try {
      await api(`/api/users/${id}`, { method: 'PATCH', body: JSON.stringify({
        role: document.querySelector(`[data-user-role="${id}"]`).value,
        active: document.querySelector(`[data-user-active="${id}"]`).value === 'true'
      }) });
      showToast('Account permissions updated.');
      await openPage(page);
    } catch (error) {
      showToast(error.message, true);
    }
  }));
  document.getElementById('create-schedule-button')?.addEventListener('click', () => showScheduleEditor());
}

function bindAppointmentActions() {
  const main = document.getElementById('main-content');
  main.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
    const item = appointments.find(appointment => appointment.id === button.dataset.view);
    if (!item) return;
    page = 'details';
    document.getElementById('page-title').textContent = 'Appointment details';
    document.getElementById('breadcrumb-current').textContent = 'Appointment details';
    main.innerHTML = renderDetails(item);
    bindPageEvents();
  }));
  main.querySelectorAll('[data-review]').forEach(button => {
    if (button.dataset.bound) return;
    button.dataset.bound = 'true';
    button.addEventListener('click', async () => {
      let reason = '';
      if (button.dataset.action === 'reject') {
        reason = window.prompt('Enter a reason for rejecting this appointment:') || '';
        if (!reason.trim()) return;
      }
      try {
        await api(`/api/appointments/${button.dataset.review}/action`, { method: 'POST', body: JSON.stringify({ action: button.dataset.action, reason }) });
        showToast('Appointment status updated.');
        await openPage(page);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
}

function fillScheduleOptions(preselected = '') {
  const service = document.getElementById('booking-service');
  const select = document.getElementById('booking-schedule');
  if (!service || !select) return;
  const matches = schedules.filter(item => item.service === service.value && item.remaining > 0);
  select.innerHTML = `<option value="">${matches.length ? 'Select an available schedule' : 'No appointment times available yet'}</option>${matches.map(item => `<option value="${item.id}" ${String(item.id) === String(preselected) ? 'selected' : ''}>${formatDate(item.date)} · ${formatTime(item.start)}–${formatTime(item.end)} · ${item.remaining} of ${item.capacity} slots left</option>`).join('')}`;
  updateSummary();
}

function bindScheduleActions() {
  document.querySelectorAll('#main-content [data-book-schedule]').forEach(button => {
    if (button.dataset.bound) return;
    button.dataset.bound = 'true';
    button.addEventListener('click', () => {
      const id = button.dataset.bookSchedule;
      openPage('book').then(() => {
        const chosen = schedules.find(item => String(item.id) === id);
        if (!chosen) return;
        document.getElementById('booking-service').value = chosen.service;
        fillScheduleOptions(chosen.id);
      });
    });
  });
  document.querySelectorAll('#main-content [data-edit-schedule]').forEach(button => {
    button.addEventListener('click', () => {
      const item = schedules.find(schedule => String(schedule.id) === button.dataset.editSchedule);
      if (item) showScheduleEditor(item);
    });
  });
}

function showScheduleEditor(item = null) {
  const host = document.getElementById('schedule-editor');
  if (!host) return;
  const editing = Boolean(item);
  const services = clinicServices;
  host.innerHTML = `<form id="schedule-form" class="panel booking-form" style="margin-bottom:15px"><h3>${editing ? 'Edit schedule' : 'Create schedule'}</h3><label for="schedule-service-edit">Clinic service</label><select id="schedule-service-edit" required>${services.map(s => `<option ${item?.service === s ? 'selected' : ''}>${escapeHtml(s)}</option>`).join('')}</select><label for="schedule-date-edit">Date</label><input class="field-control" id="schedule-date-edit" type="date" min="${localDateString()}" required value="${item?.date || ''}"><label for="schedule-start-edit">Start time</label><input class="field-control" id="schedule-start-edit" type="time" required value="${item?.start || ''}"><label for="schedule-end-edit">End time</label><input class="field-control" id="schedule-end-edit" type="time" required value="${item?.end || ''}"><label for="schedule-capacity-edit">Appointment capacity</label><input class="field-control" id="schedule-capacity-edit" type="number" min="1" max="200" required value="${item?.capacity || 10}"><div class="form-actions"><button class="button button-secondary" type="button" id="cancel-schedule-edit">Cancel</button><button class="button button-primary" type="submit">Save schedule</button></div></form>`;
  document.getElementById('cancel-schedule-edit').addEventListener('click', () => { host.innerHTML = ''; });
  document.getElementById('schedule-form').addEventListener('submit', async event => {
    event.preventDefault();
    const payload = {
      service: document.getElementById('schedule-service-edit').value,
      date: document.getElementById('schedule-date-edit').value,
      start: document.getElementById('schedule-start-edit').value,
      end: document.getElementById('schedule-end-edit').value,
      capacity: Number(document.getElementById('schedule-capacity-edit').value),
      active: true
    };
    try {
      await api(editing ? `/api/schedules/${item.id}` : '/api/schedules', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(payload) });
      showToast(editing ? 'Schedule updated.' : 'Schedule created.');
      await openPage('schedules');
    } catch (error) {
      showToast(error.message, true);
    }
  });
}

async function showLogin() {
  user = null;
  document.getElementById('app-shell').classList.add('hidden');
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('register-form').classList.add('hidden');
  document.getElementById('login-form').classList.remove('hidden');
}

async function setupFirebaseGoogleSignIn() {
  const section = document.getElementById('firebase-signin-section');
  const message = document.getElementById('firebase-login-message');
  try {
    let firebaseConfig = window.CAMPUS_CLINIC_FIREBASE_CONFIG;
    if (!firebaseConfig?.apiKey || !firebaseConfig?.authDomain || !firebaseConfig?.projectId || !firebaseConfig?.appId) {
      ({ firebaseConfig } = await api('/api/auth/config'));
    }
    if (!firebaseConfig) return;

    section.classList.remove('hidden');
    document.getElementById('firebase-google-login').addEventListener('click', async event => {
      const button = event.currentTarget;
      button.disabled = true;
      message.textContent = '';
      try {
        const { signInWithGoogle } = await import('./firebase-auth.js');
        const idToken = await signInWithGoogle(firebaseConfig);
        const result = await api('/api/login/firebase', {
          method: 'POST',
          body: JSON.stringify({ idToken })
        });
        csrfToken = result.csrfToken;
        user = result.user;
        document.getElementById('login-screen').classList.add('hidden');
        document.getElementById('app-shell').classList.remove('hidden');
        updateHeader();
        await openPage('dashboard');
      } catch (error) {
        message.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  } catch (error) {
    document.getElementById('login-message').textContent =
      `Firebase sign-in configuration could not be loaded: ${error.message}`;
  }
}

async function startSession() {
  try {
    const result = await api('/api/session');
    csrfToken = result.csrfToken;
    user = result.user;
    if (!user) setupFirebaseGoogleSignIn();
    if (user) {
      document.getElementById('login-screen').classList.add('hidden');
      document.getElementById('app-shell').classList.remove('hidden');
      updateHeader();
      await openPage('dashboard');
    }
  } catch (error) {
    document.getElementById('login-message').textContent = `Cannot reach the clinic server: ${error.message}`;
    setupFirebaseGoogleSignIn();
  }
}

function bindScheduleBookButtons() {
  bindScheduleActions();
}

function bindInitialControls() {
  bindPasswordToggles(document);
  document.getElementById('login-form').addEventListener('submit', async event => {
    event.preventDefault();
    const message = document.getElementById('login-message');
    message.textContent = '';
    try {
      const result = await api('/api/login', { method: 'POST', body: JSON.stringify({
        identity: document.getElementById('login-email').value.trim(),
        password: document.getElementById('login-password').value
      }) });
      csrfToken = result.csrfToken;
      user = result.user;
      document.getElementById('login-password').value = '';
      document.getElementById('login-screen').classList.add('hidden');
      document.getElementById('app-shell').classList.remove('hidden');
      updateHeader();
      await openPage('dashboard');
    } catch (error) {
      message.textContent = error.message;
    }
  });
  document.getElementById('register-link').addEventListener('click', event => {
    event.preventDefault();
    document.getElementById('login-form').classList.add('hidden');
    document.getElementById('register-form').classList.remove('hidden');
  });
  document.getElementById('login-link').addEventListener('click', event => {
    event.preventDefault();
    document.getElementById('register-form').classList.add('hidden');
    document.getElementById('login-form').classList.remove('hidden');
  });
  document.getElementById('register-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    try {
      const result = await api('/api/register', { method: 'POST', body: JSON.stringify({
        name: document.getElementById('register-name').value.trim(),
        schoolId: document.getElementById('register-id').value.trim(),
        email: document.getElementById('register-email').value.trim(),
        password: document.getElementById('register-password').value,
        role: document.getElementById('register-role').value
      }) });
      csrfToken = result.csrfToken;
      user = result.user;
      document.getElementById('login-screen').classList.add('hidden');
      document.getElementById('app-shell').classList.remove('hidden');
      updateHeader();
      await openPage('dashboard');
    } catch (error) {
      document.getElementById('register-message').textContent = error.message;
    }
  });
  document.getElementById('logout-button').addEventListener('click', async () => {
    try {
      await api('/api/logout', { method: 'POST', body: '{}' });
      await api('/api/session').then(result => { csrfToken = result.csrfToken; });
      await showLogin();
    } catch (error) {
      showToast(error.message, true);
    }
  });
  document.getElementById('profile-button').addEventListener('click', () => {
    document.getElementById('profile-menu').classList.toggle('hidden');
    document.getElementById('notification-popover').classList.add('hidden');
  });
  document.getElementById('notification-button').addEventListener('click', () => {
    document.getElementById('notification-popover').classList.toggle('hidden');
    document.getElementById('profile-menu').classList.add('hidden');
    const content = document.querySelector('#notification-popover .muted');
    content.textContent = appointments.length ? `You have ${appointments.length} appointment update${appointments.length === 1 ? '' : 's'}. Open Notifications to view details.` : "You're all caught up. New appointment updates will appear here.";
  });
  document.getElementById('menu-toggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.add('open');
    document.getElementById('sidebar-scrim').classList.add('visible');
  });
  document.getElementById('sidebar-scrim').addEventListener('click', () => {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-scrim').classList.remove('visible');
  });
  document.getElementById('sidebar-nav').addEventListener('click', event => {
    const button = event.target.closest('[data-page]');
    if (button) openPage(button.dataset.page);
  });
}

function bindPasswordToggles(root) {
  root.querySelectorAll('[data-toggle-password]').forEach(button => {
    if (button.dataset.bound) return;
    button.dataset.bound = 'true';
    button.addEventListener('click', event => {
      const password = document.getElementById(event.currentTarget.dataset.togglePassword);
      const shown = password.type === 'password';
      password.type = shown ? 'text' : 'password';
      event.currentTarget.textContent = shown ? 'Hide' : 'Show';
      event.currentTarget.setAttribute('aria-label', shown ? 'Hide password' : 'Show password');
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  bindInitialControls();
  startSession();
});
