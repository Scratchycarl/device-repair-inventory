document.addEventListener('DOMContentLoaded', () => {
    const tableBody = document.getElementById('inventory-body');
    const partsSummaryBody = document.getElementById('parts-summary-body');
    const partsSummaryCount = document.getElementById('parts-summary-count');
    const panelInventory = document.getElementById('panel-inventory');
    const panelParts = document.getElementById('panel-parts');
    const tabInventory = document.getElementById('tab-inventory');
    const tabParts = document.getElementById('tab-parts');
    const modal = document.getElementById('detail-modal');

    const COMMON_PARTS = [
        'OLED Assembly',
        'LCD Assembly',
        'Digitizer',
        'Display Assembly',
        'Back Glass',
        'Back Cover',
        'Back Housing',
        'Replacement Battery',
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
        modelName: document.getElementById('modal-model-name'),
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
        } catch (error) {
            console.error('Error fetching inventory:', error);
            tableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-center text-sm text-red-500">Failed to load inventory.</td></tr>`;
        }
    }

    function renderTable() {
        if (inventoryData.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-center text-sm text-gray-500">No devices in inventory yet.</td></tr>`;
            return;
        }

        tableBody.innerHTML = inventoryData.map((item) => {
            const blocked = isBlockedLock(item.lock_status);
            const parts = parseParts(item.parts_needed);
            const partsStr = blocked
                ? 'Excluded'
                : (parts.length > 0 ? parts.join(', ') : 'None');
            const rowClass = blocked
                ? 'table-row-hover bg-red-50'
                : 'table-row-hover';
            const lockClass = blocked
                ? 'bg-red-100 text-red-800'
                : 'bg-green-100 text-green-800';

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
                const item = inventoryData.find((i) => i.id === id);
                if (item) openModal(item);
            });
        });
    }

    function renderPartsSummary() {
        const aggregates = new Map();

        inventoryData.forEach((item) => {
            if (isBlockedLock(item.lock_status)) return;
            const parts = parseParts(item.parts_needed);
            const deviceLabel = `#${item.id} ${item.model || 'Unknown'}`.trim();
            parts.forEach((part) => {
                const key = part.trim();
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

    function isBlockedLock(status) {
        return status === 'Locked (FMI ON)' || status === 'Bypassed';
    }

    function styleLockSelect(select) {
        const blocked = isBlockedLock(select.value);
        select.classList.toggle('bg-red-50', blocked);
        select.classList.toggle('border-red-400', blocked);
        select.classList.toggle('text-red-800', blocked);
        select.classList.toggle('font-semibold', blocked);
    }

    function parseParts(raw) {
        try {
            const parsed = JSON.parse(raw || '[]');
            return Array.isArray(parsed) ? parsed.map(String) : [];
        } catch (e) {
            return [];
        }
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

        elements.partsGrid.innerHTML = currentParts.map((part, index) => `
            <div class="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-2 py-1.5" data-index="${index}">
                <input type="text" value="${escapeAttr(part)}" data-index="${index}"
                    class="part-name-input flex-1 min-w-0 bg-transparent text-sm text-gray-800 border-0 focus:ring-0 focus:outline-none px-1">
                <button type="button" data-index="${index}" class="btn-remove-part text-red-500 hover:text-red-700 text-sm font-bold px-2 py-1" title="Remove">
                    ×
                </button>
            </div>
        `).join('');

        elements.partsGrid.querySelectorAll('.part-name-input').forEach((input) => {
            input.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.index, 10);
                const value = e.target.value.trim();
                if (!value) {
                    currentParts.splice(idx, 1);
                } else {
                    currentParts[idx] = value;
                }
                renderPartsEditor();
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
        const exists = currentParts.some((p) => p.toLowerCase() === cleaned.toLowerCase());
        if (exists) return;
        currentParts.push(cleaned);
        renderPartsEditor();
    }

    function openModal(item) {
        currentItemId = item.id;
        currentParts = parseParts(item.parts_needed);

        elements.modelName.innerText = item.model || 'Unknown Device';
        elements.color.innerText = item.color || '-';
        elements.capacity.innerText = item.capacity || '-';
        elements.battery.innerText = item.battery_health || '-';
        elements.inventoryNumber.innerText = item.inventory_number || '-';
        elements.ios.innerText = item.ios_version || '-';
        elements.serial.innerText = item.serial_number || '-';
        elements.imei.innerText = item.imei || '-';
        elements.date.innerText = item.date_received || '-';
        elements.visionType.innerText = item.vision_device_type || '-';
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
                currentParts[idx] = input.value.trim();
            }
        });
        currentParts = currentParts.filter(Boolean);

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
                }),
            });
            const result = await res.json();
            if (!res.ok) {
                throw new Error(result.message || 'Save failed');
            }

            const idx = inventoryData.findIndex((i) => i.id === currentItemId);
            if (idx >= 0) inventoryData[idx] = result.item;
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
        const label = item ? (item.model || `Device #${currentItemId}`) : `Device #${currentItemId}`;
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
    elements.lockStatus.addEventListener('change', () => styleLockSelect(elements.lockStatus));

    elements.btnSave.addEventListener('click', saveItem);
    elements.btnDelete.addEventListener('click', deleteItem);
    document.getElementById('btn-close-modal').addEventListener('click', closeModal);
    document.getElementById('btn-close-modal-bottom').addEventListener('click', closeModal);
    document.getElementById('modal-overlay').addEventListener('click', closeModal);

    loadInventory();
});
