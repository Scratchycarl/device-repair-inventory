document.addEventListener('DOMContentLoaded', () => {
    const tableBody = document.getElementById('inventory-body');
    const partsSummaryBody = document.getElementById('parts-summary-body');
    const partsSummaryCount = document.getElementById('parts-summary-count');
    const panelInventory = document.getElementById('panel-inventory');
    const panelParts = document.getElementById('panel-parts');
    const tabInventory = document.getElementById('tab-inventory');
    const tabParts = document.getElementById('tab-parts');
    const searchInput = document.getElementById('inventory-search');
    const sortSelect = document.getElementById('inventory-sort');
    const searchStatus = document.getElementById('inventory-search-status');
    const modal = document.getElementById('detail-modal');
    const jobList = document.getElementById('job-list');
    const jobPanelSubtitle = document.getElementById('job-panel-subtitle');
    const jobPanelFooter = document.getElementById('job-panel-footer');
    const btnOpenDevice = document.getElementById('btn-open-device');
    const customJobInput = document.getElementById('custom-job-input');
    const btnAddJob = document.getElementById('btn-add-job');
    const taobaoModal = document.getElementById('taobao-modal');

    const SCREEN_PARTS = new Set(['OLED Assembly', 'LCD Assembly', 'Digitizer', 'Display Assembly']);

    const COMMON_PARTS = [
        'OLED Assembly',
        'LCD Assembly',
        'Digitizer',
        'Display Assembly',
        'Back Glass',
        'Back Cover',
        'Back Housing',
        'Replacement Battery',
        'LiDAR Module',
        'Camera Module',
        'Rear Camera Glass',
        'WiFi Antenna',
        'Power Button',
        'Power Flex',
        'Volume Flex',
        'Charging Port',
        'Loudspeaker',
        'Earpiece Speaker',
        'Microphone',
        'Face ID / TrueDepth',
        'Home Button',
        'Vibrator',
        'Logic Board Repair',
    ];

    const elements = {
        title: document.getElementById('modal-title'),
        model: document.getElementById('modal-model'),
        color: document.getElementById('modal-color'),
        capacity: document.getElementById('modal-capacity'),
        battery: document.getElementById('modal-battery'),
        inventoryNumber: document.getElementById('modal-inv'),
        ios: document.getElementById('modal-ios'),
        serial: document.getElementById('modal-serial'),
        imei: document.getElementById('modal-imei'),
        date: document.getElementById('modal-date'),
        visionType: document.getElementById('modal-vision-type'),
        remarks: document.getElementById('modal-remarks'),
        condition: document.getElementById('modal-condition'),
        lockStatus: document.getElementById('modal-lock-status'),
        partsGrid: document.getElementById('modal-parts-grid'),
        partsCount: document.getElementById('parts-count'),
        customPartInput: document.getElementById('custom-part-input'),
        commonPartsList: document.getElementById('common-parts-list'),
        quickAddParts: document.getElementById('quick-add-parts'),
        imgFront: document.getElementById('modal-img-front'),
        imgFrontPh: document.getElementById('modal-img-front-ph'),
        imgBack: document.getElementById('modal-img-back'),
        imgBackPh: document.getElementById('modal-img-back-ph'),
        btnSave: document.getElementById('btn-save-item'),
        btnAddPart: document.getElementById('btn-add-part'),
        btnDelete: document.getElementById('btn-delete-item'),
    };

    let inventoryData = [];
    let currentItemId = null;
    let selectedDeviceId = null;
    let deviceJobs = [];
    let currentParts = [];

    elements.commonPartsList.innerHTML = COMMON_PARTS
        .map((p) => `<option value="${escapeAttr(p)}"></option>`)
        .join('');

    elements.quickAddParts.innerHTML = COMMON_PARTS.map((p) => `
        <button type="button" data-part="${escapeAttr(p)}"
            class="quick-add-btn text-xs px-2.5 py-1 rounded-full border border-gray-300 bg-white text-gray-700 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-800">
            + ${escapeHtml(p)}
        </button>
    `).join('');

    function setActiveTab(tab) {
        const inventoryActive = tab === 'inventory';
        panelInventory.classList.toggle('hidden', !inventoryActive);
        panelParts.classList.toggle('hidden', inventoryActive);

        tabInventory.classList.toggle('border-blue-600', inventoryActive);
        tabInventory.classList.toggle('text-blue-700', inventoryActive);
        tabInventory.classList.toggle('border-transparent', !inventoryActive);
        tabInventory.classList.toggle('text-gray-500', !inventoryActive);

        tabParts.classList.toggle('border-blue-600', !inventoryActive);
        tabParts.classList.toggle('text-blue-700', !inventoryActive);
        tabParts.classList.toggle('border-transparent', inventoryActive);
        tabParts.classList.toggle('text-gray-500', inventoryActive);
    }

    async function loadInventory() {
        try {
            const res = await fetch('/api/inventory');
            inventoryData = await res.json();
            renderTable();
            renderPartsSummary();
            if (!selectedDeviceId && inventoryData.length > 0) {
                const sorted = sortInventoryItems(inventoryData);
                const needsRepair = sorted.find((i) => (i.pending_jobs || 0) > 0);
                selectDevice((needsRepair || sorted[0]).id);
            } else if (selectedDeviceId) {
                loadJobsForDevice(selectedDeviceId);
            }
        } catch (error) {
            console.error('Error fetching inventory:', error);
            tableBody.innerHTML = `<tr><td colspan="7" class="px-6 py-4 text-center text-sm text-red-500">Failed to load inventory.</td></tr>`;
        }
    }

    function normalizeSearchValue(value) {
        return String(value || '').toLowerCase().replace(/[\s\-]/g, '');
    }

    function matchesSearch(item, query) {
        const raw = String(query || '').trim().toLowerCase();
        if (!raw) return true;
        const compact = raw.replace(/[\s\-]/g, '');
        if (String(item.model || '').toLowerCase().includes(raw)) return true;
        if (normalizeSearchValue(item.serial_number).includes(compact)) return true;
        if (normalizeSearchValue(item.imei).includes(compact)) return true;
        return false;
    }

    function parseParts(raw) {
        try {
            const parsed = typeof raw === 'string' ? JSON.parse(raw || '[]') : (raw || []);
            if (!Array.isArray(parsed)) return [];
            return parsed.map((item) => {
                if (typeof item === 'string') {
                    const name = item.trim();
                    return name ? { name, needs_programming: false } : null;
                }
                if (item && typeof item === 'object') {
                    const name = String(item.name || '').trim();
                    if (!name) return null;
                    return { name, needs_programming: Boolean(item.needs_programming) };
                }
                return null;
            }).filter(Boolean);
        } catch (e) {
            return [];
        }
    }

    function partNamesFromRaw(raw) {
        return parseParts(raw).map((p) => p.name);
    }

    function sortInventoryItems(items) {
        const mode = sortSelect.value || 'needs_repair';
        const sorted = [...items];
        sorted.sort((a, b) => {
            if (mode === 'needs_repair') {
                const aPending = a.pending_jobs || 0;
                const bPending = b.pending_jobs || 0;
                if (aPending > 0 && bPending === 0) return -1;
                if (bPending > 0 && aPending === 0) return 1;
                if (bPending !== aPending) return bPending - aPending;
                return (b.id || 0) - (a.id || 0);
            }
            if (mode === 'date_asc') {
                return String(a.date_received || '').localeCompare(String(b.date_received || '')) || a.id - b.id;
            }
            if (mode === 'model') {
                return String(a.model || '').localeCompare(String(b.model || '')) || a.id - b.id;
            }
            // date_desc default
            return String(b.date_received || '').localeCompare(String(a.date_received || '')) || b.id - a.id;
        });
        return sorted;
    }

    function filteredInventory() {
        return sortInventoryItems(inventoryData.filter((item) => matchesSearch(item, searchInput.value)));
    }

    async function loadJobsForDevice(deviceId) {
        if (!deviceId) {
            deviceJobs = [];
            renderJobPanel();
            return;
        }
        try {
            const res = await fetch(`/api/inventory/${deviceId}/jobs`);
            const data = await res.json();
            deviceJobs = data.jobs || [];
            renderJobPanel();
        } catch (err) {
            console.error('Failed to load jobs', err);
            jobList.innerHTML = '<p class="text-sm text-red-500">Failed to load jobs.</p>';
        }
    }

    function selectDevice(deviceId) {
        selectedDeviceId = deviceId;
        renderTable();
        loadJobsForDevice(deviceId);
    }

    function renderJobPanel() {
        const item = inventoryData.find((i) => i.id === selectedDeviceId);
        if (!item) {
            jobPanelSubtitle.textContent = 'Select a device to view its checklist.';
            btnOpenDevice.classList.add('hidden');
            jobPanelFooter.classList.add('hidden');
            jobList.innerHTML = '<p class="text-sm text-gray-400 italic">No device selected.</p>';
            return;
        }

        const label = item.model || `Device #${item.id}`;
        const pending = item.pending_jobs || 0;
        const total = item.total_jobs || 0;
        jobPanelSubtitle.textContent = `${label} · ${pending} pending / ${total} total`;
        btnOpenDevice.classList.remove('hidden');
        jobPanelFooter.classList.remove('hidden');

        if (deviceJobs.length === 0) {
            jobList.innerHTML = '<p class="text-sm text-gray-400 italic">No jobs yet. Save parts on this device to generate tasks.</p>';
            return;
        }

        jobList.innerHTML = deviceJobs.map((job) => {
            const done = job.status === 'done';
            const taobaoHint = job.taobao_order_id
                ? `<span class="text-xs text-emerald-600 block mt-0.5">Taobao ${escapeHtml(job.taobao_order_id)}</span>`
                : '';
            return `
                <label class="flex items-start gap-3 p-2 rounded-lg border ${done ? 'border-gray-200 bg-gray-50' : 'border-gray-200 bg-white hover:bg-blue-50'} cursor-pointer">
                    <input type="checkbox" class="job-checkbox mt-1 rounded border-gray-300 text-blue-600" data-job-id="${job.id}" ${done ? 'checked' : ''}>
                    <span class="flex-1 min-w-0">
                        <span class="text-sm ${done ? 'job-done' : 'text-gray-900'}">${escapeHtml(job.title)}</span>
                        ${taobaoHint}
                    </span>
                    ${job.job_type === 'custom' ? `<button type="button" class="btn-delete-job text-xs text-red-500 hover:text-red-700" data-job-id="${job.id}">Del</button>` : ''}
                </label>
            `;
        }).join('');

        jobList.querySelectorAll('.job-checkbox').forEach((cb) => {
            cb.addEventListener('change', () => toggleJob(parseInt(cb.dataset.jobId, 10), cb.checked));
        });
        jobList.querySelectorAll('.btn-delete-job').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                deleteJob(parseInt(btn.dataset.jobId, 10));
            });
        });
    }

    async function toggleJob(jobId, done) {
        try {
            const res = await fetch(`/api/jobs/${jobId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: done ? 'done' : 'pending' }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || 'Update failed');
            const idx = deviceJobs.findIndex((j) => j.id === jobId);
            if (idx >= 0) deviceJobs[idx] = data.job;
            await refreshInventoryCounts();
            renderJobPanel();
            renderTable();
        } catch (err) {
            alert(err.message || 'Failed to update job');
            loadJobsForDevice(selectedDeviceId);
        }
    }

    async function deleteJob(jobId) {
        if (!confirm('Delete this custom job?')) return;
        try {
            const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || 'Delete failed');
            deviceJobs = deviceJobs.filter((j) => j.id !== jobId);
            await refreshInventoryCounts();
            renderJobPanel();
            renderTable();
        } catch (err) {
            alert(err.message || 'Failed to delete job');
        }
    }

    async function addCustomJob() {
        const title = customJobInput.value.trim();
        if (!title || !selectedDeviceId) return;
        try {
            const res = await fetch(`/api/inventory/${selectedDeviceId}/jobs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || 'Add failed');
            deviceJobs.push(data.job);
            customJobInput.value = '';
            await refreshInventoryCounts();
            renderJobPanel();
            renderTable();
        } catch (err) {
            alert(err.message || 'Failed to add job');
        }
    }

    async function refreshInventoryCounts() {
        const res = await fetch('/api/inventory');
        inventoryData = await res.json();
        renderPartsSummary();
    }

    function renderTable() {
        const items = filteredInventory();
        const query = searchInput.value.trim();
        if (query) {
            searchStatus.classList.remove('hidden');
            searchStatus.textContent = items.length
                ? `${items.length} match${items.length === 1 ? '' : 'es'}`
                : 'No matching devices';
        } else {
            searchStatus.classList.add('hidden');
            searchStatus.textContent = '';
        }

        if (inventoryData.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="7" class="px-6 py-4 text-center text-sm text-gray-500">No devices in inventory yet.</td></tr>`;
            return;
        }

        if (items.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="7" class="px-6 py-4 text-center text-sm text-gray-500">No devices match "${escapeHtml(query)}".</td></tr>`;
            return;
        }

        tableBody.innerHTML = items.map((item) => {
            const blocked = isBlockedLock(item.lock_status, item);
            const parts = parseParts(item.parts_needed);
            const partsStr = blocked
                ? 'Excluded'
                : (parts.length > 0 ? parts.map((p) => p.name).join(', ') : 'None');
            const selected = item.id === selectedDeviceId;
            const pending = item.pending_jobs || 0;
            const total = item.total_jobs || 0;
            const rowClass = [
                'table-row-hover',
                blocked ? 'bg-red-50' : '',
                selected ? 'table-row-selected' : '',
            ].filter(Boolean).join(' ');
            const lockClass = blocked
                ? 'bg-red-100 text-red-800'
                : 'bg-green-100 text-green-800';
            const jobBadge = total === 0
                ? '<span class="text-xs text-gray-400">—</span>'
                : pending > 0
                    ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800">${pending} left</span>`
                    : `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-800">Done</span>`;

            return `
                <tr class="${rowClass}" data-id="${item.id}">
                    <td class="px-6 py-4 whitespace-nowrap text-sm ${blocked ? 'text-red-700' : 'text-gray-500'}">
                        #${item.id}<br><span class="text-xs ${blocked ? 'text-red-400' : 'text-gray-400'}">${item.date_received || ''}</span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <div class="text-sm font-medium ${blocked ? 'text-red-900' : 'text-gray-900'}">${escapeHtml(item.model || 'Unknown')}</div>
                        <div class="text-sm ${blocked ? 'text-red-700' : 'text-gray-500'}">${item.inventory_number ? '#' + escapeHtml(item.inventory_number) + ' · ' : ''}${escapeHtml(item.color || '')} ${escapeHtml(item.capacity || '')} ${item.vision_device_type ? '· ' + escapeHtml(item.vision_device_type) : ''}</div>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm ${blocked ? 'text-red-700' : 'text-gray-500'}">
                        S/N: ${escapeHtml(item.serial_number || 'N/A')}<br>
                        IMEI: ${escapeHtml(item.imei || 'N/A')}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">${jobBadge}</td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${lockClass}">
                            ${escapeHtml(item.lock_status || 'Unknown')}
                        </span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
                            ${escapeHtml(item.damage_condition || 'Unknown')}
                        </span>
                    </td>
                    <td class="px-6 py-4 text-sm ${blocked ? 'text-red-600 italic' : 'text-gray-500'} truncate max-w-xs">
                        ${escapeHtml(partsStr)}
                    </td>
                </tr>
            `;
        }).join('');

        document.querySelectorAll('.table-row-hover').forEach((row) => {
            row.addEventListener('click', () => {
                const id = parseInt(row.getAttribute('data-id'), 10);
                selectDevice(id);
            });
            row.addEventListener('dblclick', () => {
                const id = parseInt(row.getAttribute('data-id'), 10);
                const item = inventoryData.find((i) => i.id === id);
                if (item) openModal(item);
            });
        });
    }

    function renderPartsSummary() {
        const aggregates = new Map();

        inventoryData.forEach((item) => {
            if (isBlockedLock(item.lock_status, item)) return;
            const parts = parseParts(item.parts_needed);
            const deviceLabel = `#${item.id} ${item.model || 'Unknown'}`.trim();
            parts.forEach((part) => {
                const key = part.name.trim();
                if (!key) return;
                if (!aggregates.has(key)) {
                    aggregates.set(key, { part: key, qty: 0, devices: [] });
                }
                const entry = aggregates.get(key);
                entry.qty += 1;
                entry.devices.push(deviceLabel);
            });
        });

        const rows = Array.from(aggregates.values()).sort((a, b) => {
            if (b.qty !== a.qty) return b.qty - a.qty;
            return a.part.localeCompare(b.part);
        });

        const totalQty = rows.reduce((sum, row) => sum + row.qty, 0);
        partsSummaryCount.textContent = rows.length
            ? `${rows.length} part type${rows.length === 1 ? '' : 's'} · ${totalQty} total`
            : '';

        if (rows.length === 0) {
            partsSummaryBody.innerHTML = `<tr><td colspan="3" class="px-6 py-4 text-center text-sm text-gray-500">No parts needed yet.</td></tr>`;
            return;
        }

        partsSummaryBody.innerHTML = rows.map((row) => `
            <tr>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">${escapeHtml(row.part)}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    <span class="inline-flex items-center justify-center min-w-[2rem] px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 text-xs font-semibold">${row.qty}</span>
                </td>
                <td class="px-6 py-4 text-sm text-gray-500">${escapeHtml(row.devices.join(', '))}</td>
            </tr>
        `).join('');
    }

    function isTablet(item) {
        const type = String(item?.vision_device_type || '').toLowerCase();
        if (type === 'tablet') return true;
        return /ipad|tablet/i.test(item?.model || '');
    }

    function isBlockedLock(status, item) {
        if (status === 'Locked (FMI ON)') return true;
        if (status === 'Bypassed' && !isTablet(item)) return true;
        return false;
    }

    function currentModalItem() {
        const item = inventoryData.find((i) => i.id === currentItemId) || {};
        return {
            ...item,
            model: elements.model.value,
            vision_device_type: elements.visionType.value,
        };
    }

    function styleLockSelect(select) {
        const blocked = isBlockedLock(select.value, currentModalItem());
        select.classList.toggle('bg-red-50', blocked);
        select.classList.toggle('border-red-400', blocked);
        select.classList.toggle('text-red-800', blocked);
        select.classList.toggle('font-semibold', blocked);
    }

    function renderPartsEditor() {
        elements.partsCount.textContent = `${currentParts.length} part${currentParts.length === 1 ? '' : 's'}`;

        if (currentParts.length === 0) {
            elements.partsGrid.innerHTML = `
                <div class="col-span-full text-sm text-gray-500 italic py-2">
                    No parts on the repair list yet. Add from quick picks or type a custom part.
                </div>`;
            return;
        }

        elements.partsGrid.innerHTML = currentParts.map((part, index) => {
            const showProgram = SCREEN_PARTS.has(part.name);
            return `
            <div class="flex flex-col gap-1 bg-gray-50 border border-gray-200 rounded-lg px-2 py-2" data-index="${index}">
                <div class="flex items-center gap-2">
                    <input type="text" value="${escapeAttr(part.name)}" data-index="${index}"
                        class="part-name-input flex-1 min-w-0 bg-transparent text-sm text-gray-800 border-0 focus:ring-0 focus:outline-none px-1">
                    <button type="button" data-index="${index}" class="btn-remove-part text-red-500 hover:text-red-700 text-sm font-bold px-2 py-1" title="Remove">×</button>
                </div>
                ${showProgram ? `
                <label class="flex items-center gap-2 text-xs text-gray-600 pl-1">
                    <input type="checkbox" class="part-program-input rounded border-gray-300 text-blue-600" data-index="${index}" ${part.needs_programming ? 'checked' : ''}>
                    Needs programming (True Tone / display config)
                </label>` : ''}
            </div>`;
        }).join('');

        elements.partsGrid.querySelectorAll('.part-name-input').forEach((input) => {
            input.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.index, 10);
                const value = e.target.value.trim();
                if (!value) {
                    currentParts.splice(idx, 1);
                } else {
                    currentParts[idx] = { ...currentParts[idx], name: value };
                }
                renderPartsEditor();
            });
        });

        elements.partsGrid.querySelectorAll('.part-program-input').forEach((input) => {
            input.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.index, 10);
                currentParts[idx] = { ...currentParts[idx], needs_programming: e.target.checked };
            });
        });

        elements.partsGrid.querySelectorAll('.btn-remove-part').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(e.currentTarget.dataset.index, 10);
                currentParts.splice(idx, 1);
                renderPartsEditor();
            });
        });
    }

    function addPart(name) {
        const cleaned = (name || '').trim();
        if (!cleaned) return;
        const exists = currentParts.some((p) => p.name.toLowerCase() === cleaned.toLowerCase());
        if (exists) return;
        currentParts.push({ name: cleaned, needs_programming: false });
        renderPartsEditor();
    }

    function openModal(item) {
        currentItemId = item.id;
        currentParts = parseParts(item.parts_needed);

        elements.title.innerText = item.model ? item.model : `Device #${item.id}`;
        elements.model.value = item.model || '';
        elements.color.value = item.color || '';
        elements.capacity.value = item.capacity || '';
        elements.battery.value = item.battery_health || '';
        elements.inventoryNumber.value = item.inventory_number || '';
        elements.ios.value = item.ios_version || '';
        elements.serial.value = item.serial_number || '';
        elements.imei.value = item.imei || '';
        elements.date.value = item.date_received || '';
        elements.visionType.value = item.vision_device_type || '';
        if (item.vision_device_type && elements.visionType.value !== item.vision_device_type) {
            const extra = document.createElement('option');
            extra.value = item.vision_device_type;
            extra.textContent = item.vision_device_type;
            elements.visionType.appendChild(extra);
            elements.visionType.value = item.vision_device_type;
        }
        elements.remarks.value = item.remarks || '';
        elements.condition.value = item.damage_condition || '';
        elements.lockStatus.value = item.lock_status || '';
        styleLockSelect(elements.lockStatus);
        elements.customPartInput.value = '';
        elements.btnSave.disabled = false;
        elements.btnSave.textContent = 'Save Changes';

        renderPartsEditor();

        if (item.front_image_url) {
            elements.imgFront.src = item.front_image_url;
            elements.imgFront.classList.remove('hidden');
            elements.imgFrontPh.classList.add('hidden');
        } else {
            elements.imgFront.classList.add('hidden');
            elements.imgFrontPh.classList.remove('hidden');
        }

        if (item.back_image_url) {
            elements.imgBack.src = item.back_image_url;
            elements.imgBack.classList.remove('hidden');
            elements.imgBackPh.classList.add('hidden');
        } else {
            elements.imgBack.classList.add('hidden');
            elements.imgBackPh.classList.remove('hidden');
        }

        modal.classList.remove('hidden');
    }

    function closeModal() {
        modal.classList.add('hidden');
        currentItemId = null;
    }

    async function saveItem() {
        if (!currentItemId) return;

        elements.partsGrid.querySelectorAll('.part-name-input').forEach((input) => {
            const idx = parseInt(input.dataset.index, 10);
            if (!Number.isNaN(idx) && currentParts[idx] !== undefined) {
                currentParts[idx] = { ...currentParts[idx], name: input.value.trim() };
            }
        });
        elements.partsGrid.querySelectorAll('.part-program-input').forEach((input) => {
            const idx = parseInt(input.dataset.index, 10);
            if (!Number.isNaN(idx) && currentParts[idx] !== undefined) {
                currentParts[idx] = { ...currentParts[idx], needs_programming: input.checked };
            }
        });
        currentParts = currentParts.filter((p) => p.name);

        elements.btnSave.disabled = true;
        elements.btnSave.textContent = 'Saving...';

        try {
            const res = await fetch(`/api/inventory/${currentItemId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    parts_needed: currentParts,
                    remarks: elements.remarks.value,
                    damage_condition: elements.condition.value.trim(),
                    lock_status: elements.lockStatus.value,
                    model: elements.model.value.trim(),
                    color: elements.color.value.trim(),
                    capacity: elements.capacity.value.trim(),
                    serial_number: elements.serial.value.trim(),
                    ios_version: elements.ios.value.trim(),
                    imei: elements.imei.value.trim(),
                    battery_health: elements.battery.value.trim(),
                    date_received: elements.date.value.trim(),
                    inventory_number: elements.inventoryNumber.value.trim(),
                    vision_device_type: elements.visionType.value.trim(),
                }),
            });
            const result = await res.json();
            if (!res.ok) {
                throw new Error(result.message || 'Save failed');
            }

            const idx = inventoryData.findIndex((i) => i.id === currentItemId);
            if (idx >= 0) inventoryData[idx] = result.item;
            if (selectedDeviceId === currentItemId) {
                await loadJobsForDevice(currentItemId);
            }
            elements.title.innerText = result.item.model || `Device #${currentItemId}`;
            renderTable();
            renderPartsSummary();
            elements.btnSave.textContent = 'Saved';
            setTimeout(() => {
                elements.btnSave.disabled = false;
                elements.btnSave.textContent = 'Save Changes';
            }, 900);
        } catch (error) {
            console.error('Save error:', error);
            alert(error.message || 'Failed to save changes');
            elements.btnSave.disabled = false;
            elements.btnSave.textContent = 'Save Changes';
        }
    }

    async function deleteItem() {
        if (!currentItemId) return;
        const item = inventoryData.find((i) => i.id === currentItemId);
        const label = item ? (elements.model.value.trim() || item.model || `Device #${currentItemId}`) : `Device #${currentItemId}`;
        if (!confirm(`Delete ${label}? This cannot be undone.`)) return;

        elements.btnDelete.disabled = true;
        elements.btnDelete.textContent = 'Deleting...';

        try {
            const res = await fetch(`/api/inventory/${currentItemId}`, { method: 'DELETE' });
            const result = await res.json();
            if (!res.ok) {
                throw new Error(result.message || 'Delete failed');
            }
            inventoryData = inventoryData.filter((i) => i.id !== currentItemId);
            if (selectedDeviceId === currentItemId) {
                selectedDeviceId = null;
                deviceJobs = [];
                renderJobPanel();
            }
            renderTable();
            renderPartsSummary();
            closeModal();
        } catch (error) {
            console.error('Delete error:', error);
            alert(error.message || 'Failed to delete device');
        } finally {
            elements.btnDelete.disabled = false;
            elements.btnDelete.textContent = 'Delete Device';
        }
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function escapeAttr(value) {
        return escapeHtml(value).replace(/'/g, '&#39;');
    }

    elements.btnAddPart.addEventListener('click', () => {
        addPart(elements.customPartInput.value);
        elements.customPartInput.value = '';
        elements.customPartInput.focus();
    });

    elements.customPartInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addPart(elements.customPartInput.value);
            elements.customPartInput.value = '';
        }
    });

    elements.quickAddParts.addEventListener('click', (e) => {
        const btn = e.target.closest('.quick-add-btn');
        if (!btn) return;
        addPart(btn.dataset.part);
    });

    tabInventory.addEventListener('click', () => setActiveTab('inventory'));
    tabParts.addEventListener('click', () => setActiveTab('parts'));
    searchInput.addEventListener('input', renderTable);
    sortSelect.addEventListener('change', renderTable);
    btnOpenDevice.addEventListener('click', () => {
        const item = inventoryData.find((i) => i.id === selectedDeviceId);
        if (item) openModal(item);
    });
    btnAddJob.addEventListener('click', addCustomJob);
    customJobInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); addCustomJob(); }
    });

    document.getElementById('btn-taobao-import').addEventListener('click', () => {
        taobaoModal.classList.remove('hidden');
        document.getElementById('taobao-results').classList.add('hidden');
    });
    document.getElementById('btn-taobao-close').addEventListener('click', () => taobaoModal.classList.add('hidden'));
    document.getElementById('taobao-overlay').addEventListener('click', () => taobaoModal.classList.add('hidden'));
    document.getElementById('btn-taobao-upload').addEventListener('click', async () => {
        const fileInput = document.getElementById('taobao-file');
        const resultsEl = document.getElementById('taobao-results');
        if (!fileInput.files || !fileInput.files[0]) {
            alert('Choose an .xlsx file first');
            return;
        }
        const form = new FormData();
        form.append('file', fileInput.files[0]);
        const btn = document.getElementById('btn-taobao-upload');
        btn.disabled = true;
        btn.textContent = 'Importing…';
        try {
            const res = await fetch('/api/taobao/import', { method: 'POST', body: form });
            const data = await res.json();
            if (!res.ok) throw new Error(data.message || 'Import failed');
            await loadInventory();
            if (selectedDeviceId) await loadJobsForDevice(selectedDeviceId);
            resultsEl.classList.remove('hidden');
            const lines = (data.results || []).map((r) => {
                if (r.status === 'matched') {
                    const jobs = (r.matched_jobs || []).map((m) => `#${m.inventory_id} ${m.part_name}`).join(', ');
                    return `✅ ${escapeHtml(r.product_name.slice(0, 40))}… → ${jobs}`;
                }
                if (r.status === 'skipped_duplicate') return `⏭ ${escapeHtml(r.order_id)} (already imported)`;
                return `❌ ${escapeHtml(r.product_name.slice(0, 40))}… — no match (${escapeHtml(r.inferred_part || 'unknown part')})`;
            });
            resultsEl.innerHTML = `<p class="font-semibold mb-2">Matched ${data.matched_count} of ${data.total_rows} rows</p>${lines.map((l) => `<div class="py-1 border-b border-gray-200 last:border-0">${l}</div>`).join('')}`;
        } catch (err) {
            alert(err.message || 'Import failed');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Upload & Match';
        }
    });

    elements.lockStatus.addEventListener('change', () => styleLockSelect(elements.lockStatus));
    elements.model.addEventListener('input', () => {
        elements.title.innerText = elements.model.value.trim() || `Device #${currentItemId}`;
        styleLockSelect(elements.lockStatus);
    });
    elements.visionType.addEventListener('change', () => styleLockSelect(elements.lockStatus));

    elements.btnSave.addEventListener('click', saveItem);
    elements.btnDelete.addEventListener('click', deleteItem);
    document.getElementById('btn-close-modal').addEventListener('click', closeModal);
    document.getElementById('btn-close-modal-bottom').addEventListener('click', closeModal);
    document.getElementById('modal-overlay').addEventListener('click', closeModal);

    loadInventory();
});
