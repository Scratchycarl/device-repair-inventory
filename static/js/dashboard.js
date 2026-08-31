document.addEventListener('DOMContentLoaded', () => {
    const tableBody = document.getElementById('inventory-body');
    const partsSummaryList = document.getElementById('parts-summary-list');
    const partsSummaryCount = document.getElementById('parts-summary-count');
    const partsHideOrdered = document.getElementById('parts-hide-ordered');
    const panelInventory = document.getElementById('panel-inventory');
    const panelParts = document.getElementById('panel-parts');
    const tabInventory = document.getElementById('tab-inventory');
    const tabParts = document.getElementById('tab-parts');
    const searchInput = document.getElementById('inventory-search');
    const sortSelect = document.getElementById('inventory-sort');
    const searchStatus = document.getElementById('inventory-search-status');
    const showArchived = document.getElementById('show-archived');
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
    let incomingByDevice = {};
    let currentItemId = null;
    let currentParts = [];

    // How far along an order is, used to pick the most advanced status per part.
    const ORDER_PROGRESS = { paid: 1, shipped: 2, received: 3 };

    // Repair workflow states. `rank` drives the "Needs repair first" sort.
    const REPAIR_STATES = {
        ready: { label: 'Ready to fix', cls: 'bg-green-100 text-green-800', rank: 0 },
        order: { label: 'Order parts', cls: 'bg-red-100 text-red-800', rank: 1 },
        inbound: { label: 'Parts inbound', cls: 'bg-blue-100 text-blue-800', rank: 2 },
        done: { label: 'No parts needed', cls: 'bg-gray-100 text-gray-500', rank: 3 },
        blocked: { label: 'Excluded', cls: 'bg-gray-200 text-gray-600', rank: 4 },
    };

    elements.commonPartsList.innerHTML = COMMON_PARTS
        .map((p) => `<option value="${escapeAttr(p)}"></option>`)
        .join('');

    elements.quickAddParts.innerHTML = COMMON_PARTS.map((p) => `
        <button type="button" data-part="${escapeAttr(p)}"
            class="quick-add-btn text-xs px-2.5 py-1 rounded-full border border-gray-300 bg-white text-gray-700 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-800">
            + ${escapeHtml(p)}
        </button>
    `).join('');

    const panelPurchases = document.getElementById('panel-purchases');
    const tabPurchases = document.getElementById('tab-purchases');
    const panelShipments = document.getElementById('panel-shipments');
    const tabShipments = document.getElementById('tab-shipments');

    function locationStatus(item) {
        return item.location_status || 'in_storage';
    }

    function isInStorage(item) {
        return locationStatus(item) === 'in_storage';
    }

    function isShippedOut(item) {
        const status = locationStatus(item);
        return status === 'in_transit' || status === 'archived';
    }

    function setActiveTab(tab) {
        const tabs = [
            { name: 'inventory', btn: tabInventory, panel: panelInventory },
            { name: 'shipments', btn: tabShipments, panel: panelShipments },
            { name: 'parts', btn: tabParts, panel: panelParts },
            { name: 'purchases', btn: tabPurchases, panel: panelPurchases },
        ];
        tabs.forEach(({ name, btn, panel }) => {
            const active = name === tab;
            panel.classList.toggle('hidden', !active);
            btn.classList.toggle('border-blue-600', active);
            btn.classList.toggle('text-blue-700', active);
            btn.classList.toggle('border-transparent', !active);
            btn.classList.toggle('text-gray-500', !active);
        });
        if (tab === 'purchases') loadPurchases();
        if (tab === 'shipments') {
            renderShipmentPicker();
            loadShipments();
        }
    }

    async function loadInventory() {
        try {
            const [res] = await Promise.all([fetch('/api/inventory'), loadIncomingParts()]);
            inventoryData = await res.json();
            renderTable();
            renderPartsSummary();
            renderShipmentPicker();
        } catch (error) {
            console.error('Error fetching inventory:', error);
            tableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-center text-sm text-red-500">Failed to load inventory.</td></tr>`;
        }
    }

    async function loadIncomingParts() {
        try {
            const res = await fetch('/api/inventory/incoming-parts');
            incomingByDevice = await res.json();
        } catch (error) {
            console.error('Error fetching incoming parts:', error);
            incomingByDevice = {};
        }
    }

    /** Part names already covered by an order for this device -> order status. */
    function coveredParts(deviceId) {
        const covered = new Map();
        (incomingByDevice[deviceId] || []).forEach((incoming) => {
            if (!incoming.part_name) return;
            const previous = covered.get(incoming.part_name);
            const better = (ORDER_PROGRESS[incoming.order_status] || 0)
                > (ORDER_PROGRESS[previous] || 0);
            if (!previous || better) covered.set(incoming.part_name, incoming.order_status);
        });
        return covered;
    }

    function repairState(item) {
        if (isBlockedLock(item.lock_status, item)) return 'blocked';
        const parts = parseParts(item.parts_needed);
        if (parts.length === 0) return 'done';
        const covered = coveredParts(item.id);
        if (parts.some((part) => !covered.has(part))) return 'order';
        return parts.every((part) => covered.get(part) === 'received') ? 'ready' : 'inbound';
    }

    function sortInventory(items) {
        const list = items.slice();
        const newestFirst = (a, b) => b.id - a.id;

        switch (sortSelect.value) {
            case 'newest':
                return list.sort(newestFirst);
            case 'oldest':
                return list.sort((a, b) => a.id - b.id);
            case 'model':
                return list.sort((a, b) =>
                    String(a.model || '').localeCompare(String(b.model || '')) || newestFirst(a, b));
            case 'parts':
                return list.sort((a, b) =>
                    parseParts(b.parts_needed).length - parseParts(a.parts_needed).length
                    || newestFirst(a, b));
            default:
                return list.sort((a, b) => {
                    const rankDiff = REPAIR_STATES[repairState(a)].rank - REPAIR_STATES[repairState(b)].rank;
                    if (rankDiff !== 0) return rankDiff;
                    const partsDiff = parseParts(b.parts_needed).length - parseParts(a.parts_needed).length;
                    return partsDiff || newestFirst(a, b);
                });
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
        if (normalizeSearchValue(item.inventory_number).includes(compact)) return true;
        if (normalizeSearchValue(item.tracking_number).includes(compact)) return true;
        return false;
    }

    function filteredInventory() {
        return inventoryData.filter((item) => {
            if (!showArchived.checked && locationStatus(item) === 'archived') return false;
            return matchesSearch(item, searchInput.value);
        });
    }

    function renderTable() {
        const items = sortInventory(filteredInventory());
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
            tableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-center text-sm text-gray-500">No devices in inventory yet.</td></tr>`;
            return;
        }

        if (items.length === 0) {
            const archivedHidden = !showArchived.checked
                && inventoryData.some((item) => locationStatus(item) === 'archived');
            const message = query
                ? `No devices match "${escapeHtml(query)}".`
                : (archivedHidden
                    ? 'No devices in storage or transit. Check Show archived to see sent devices.'
                    : 'No devices in inventory yet.');
            tableBody.innerHTML = `<tr><td colspan="6" class="px-6 py-4 text-center text-sm text-gray-500">${message}</td></tr>`;
            return;
        }

        tableBody.innerHTML = items.map((item) => {
            const loc = locationStatus(item);
            const archived = loc === 'archived';
            const inTransit = loc === 'in_transit';
            const blocked = isBlockedLock(item.lock_status, item);
            const parts = parseParts(item.parts_needed);
            const state = REPAIR_STATES[repairState(item)];
            const partsStr = blocked
                ? 'Excluded'
                : (parts.length > 0 ? parts.join(', ') : 'None');
            const rowClass = archived
                ? 'table-row-hover bg-gray-100 hover:bg-gray-200'
                : (inTransit
                    ? 'table-row-hover bg-sky-50 hover:bg-sky-100'
                    : (blocked ? 'table-row-hover bg-red-50 hover:bg-red-100' : 'table-row-hover hover:bg-gray-50'));
            const muted = archived;
            const idClass = muted ? 'text-gray-500' : (blocked ? 'text-red-700' : 'text-gray-500');
            const modelClass = muted ? 'text-gray-600' : (blocked ? 'text-red-900' : 'text-gray-900');
            const subClass = muted ? 'text-gray-400' : (blocked ? 'text-red-700' : 'text-gray-500');
            const lockClass = blocked
                ? 'bg-red-100 text-red-800'
                : 'bg-green-100 text-green-800';
            const trackingLine = inTransit && item.tracking_number
                ? `<div class="text-xs text-sky-700 mt-1">Tracking ${escapeHtml(item.tracking_number)}</div>`
                : (archived && item.tracking_number
                    ? `<div class="text-xs text-gray-400 mt-1">Shipped ${escapeHtml(item.tracking_number)}</div>`
                    : '');

            return `
                <tr class="${rowClass}" data-id="${item.id}">
                    <td class="px-3 py-4 whitespace-nowrap text-sm ${idClass}">
                        #${item.id}<br><span class="text-xs ${muted ? 'text-gray-400' : (blocked ? 'text-red-400' : 'text-gray-400')}">${item.date_received || ''}</span>
                    </td>
                    <td class="px-3 py-4">
                        <div class="text-sm font-medium ${modelClass}">${escapeHtml(item.model || 'Unknown')}</div>
                        <div class="text-xs ${subClass}">${item.inventory_number ? '#' + escapeHtml(item.inventory_number) + ' · ' : ''}${escapeHtml(item.color || '')} ${escapeHtml(item.capacity || '')} ${item.vision_device_type ? '· ' + escapeHtml(item.vision_device_type) : ''}</div>
                        ${trackingLine}
                    </td>
                    <td class="px-3 py-4 whitespace-nowrap text-xs ${subClass}">
                        ${escapeHtml(item.serial_number || 'N/A')}<br>
                        ${escapeHtml(item.imei || 'N/A')}
                    </td>
                    <td class="px-3 py-4">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${lockClass}">
                            ${escapeHtml(item.lock_status || 'Unknown')}
                        </span>
                    </td>
                    <td class="px-3 py-4">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
                            ${escapeHtml(item.damage_condition || 'Unknown')}
                        </span>
                    </td>
                    <td class="px-3 py-4 text-sm ${blocked ? 'text-red-600 italic' : 'text-gray-500'} max-w-xs">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${state.cls}">
                            ${escapeHtml(state.label)}
                        </span>
                        <div class="truncate mt-1 text-xs">${escapeHtml(partsStr)}</div>
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

    /**
     * Group every needed part by model so the result reads as a purchase list:
     * "Replacement Battery -> 3x iPhone 7, 2x iPhone 11". Parts already covered
     * by an order are counted separately so they don't get bought twice.
     */
    function buildShoppingList() {
        const parts = new Map();

        inventoryData.forEach((item) => {
            if (isBlockedLock(item.lock_status, item)) return;
            if (isShippedOut(item)) return;
            const covered = coveredParts(item.id);

            parseParts(item.parts_needed).forEach((raw) => {
                const part = String(raw).trim();
                if (!part) return;
                if (!parts.has(part)) parts.set(part, new Map());

                const models = parts.get(part);
                const label = String(item.model || '').trim() || 'Unknown model';
                const key = label.toLowerCase().replace(/\s+/g, ' ');
                if (!models.has(key)) {
                    models.set(key, { label, toOrder: 0, ordered: 0, toOrderIds: [], orderedIds: [] });
                }

                const entry = models.get(key);
                if (covered.has(part)) {
                    entry.ordered += 1;
                    entry.orderedIds.push(item.id);
                } else {
                    entry.toOrder += 1;
                    entry.toOrderIds.push(item.id);
                }
            });
        });

        return Array.from(parts.entries()).map(([part, models]) => {
            const rows = Array.from(models.values()).sort((a, b) =>
                (b.toOrder - a.toOrder) || (b.ordered - a.ordered) || a.label.localeCompare(b.label));
            return {
                part,
                rows,
                toOrder: rows.reduce((sum, row) => sum + row.toOrder, 0),
                ordered: rows.reduce((sum, row) => sum + row.ordered, 0),
            };
        }).sort((a, b) => (b.toOrder - a.toOrder) || a.part.localeCompare(b.part));
    }

    function renderPartsSummary() {
        const hideOrdered = partsHideOrdered.checked;
        const groups = buildShoppingList().filter((group) => !hideOrdered || group.toOrder > 0);

        const totalToOrder = groups.reduce((sum, group) => sum + group.toOrder, 0);
        const totalOrdered = groups.reduce((sum, group) => sum + group.ordered, 0);
        partsSummaryCount.textContent = groups.length
            ? `${groups.length} part type${groups.length === 1 ? '' : 's'} · ${totalToOrder} to order`
                + (totalOrdered ? ` · ${totalOrdered} already ordered` : '')
            : '';

        if (groups.length === 0) {
            const message = hideOrdered && totalOrdered === 0 && inventoryData.length > 0
                ? 'Nothing to order — every needed part is already on an order.'
                : 'No parts needed yet.';
            partsSummaryList.innerHTML = `<div class="px-6 py-6 text-center text-sm text-gray-500">${message}</div>`;
            return;
        }

        partsSummaryList.innerHTML = groups.map((group) => {
            const rows = group.rows
                .map((row) => renderShoppingRow(row, hideOrdered))
                .filter(Boolean)
                .join('');
            return `
                <div class="px-6 py-4">
                    <div class="flex flex-wrap items-baseline gap-2 mb-2">
                        <h4 class="text-base font-semibold text-gray-900">${escapeHtml(group.part)}</h4>
                        <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 text-xs font-semibold">
                            ${group.toOrder} to order
                        </span>
                        ${group.ordered ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full bg-green-100 text-green-800 text-xs font-semibold">${group.ordered} ordered</span>` : ''}
                        <button type="button" class="btn-copy-part ml-auto text-xs text-gray-500 hover:text-blue-700 underline"
                            data-part="${escapeAttr(group.part)}">Copy</button>
                    </div>
                    <ul class="space-y-1">${rows}</ul>
                </div>
            `;
        }).join('');
    }

    function renderShoppingRow(row, hideOrdered) {
        const lines = [];
        if (row.toOrder > 0) {
            lines.push(`
                <li class="flex flex-wrap items-baseline gap-2 text-sm">
                    <span class="font-semibold text-gray-900 tabular-nums">${row.toOrder}×</span>
                    <span class="text-gray-800">${escapeHtml(row.label)}</span>
                    <span class="text-xs text-gray-400">${row.toOrderIds.map((id) => '#' + id).join(' ')}</span>
                </li>`);
        }
        if (!hideOrdered && row.ordered > 0) {
            lines.push(`
                <li class="flex flex-wrap items-baseline gap-2 text-sm">
                    <span class="font-semibold text-gray-400 tabular-nums">${row.ordered}×</span>
                    <span class="text-gray-400 line-through">${escapeHtml(row.label)}</span>
                    <span class="text-xs text-green-700">already ordered</span>
                    <span class="text-xs text-gray-400">${row.orderedIds.map((id) => '#' + id).join(' ')}</span>
                </li>`);
        }
        return lines.join('');
    }

    /** Plain-text version of the list, ready to paste into a shop search or notes. */
    function shoppingListText(onlyPart) {
        return buildShoppingList()
            .filter((group) => group.toOrder > 0 && (!onlyPart || group.part === onlyPart))
            .map((group) => {
                const lines = group.rows
                    .filter((row) => row.toOrder > 0)
                    .map((row) => `  ${row.toOrder}x ${row.label}`);
                return `${group.part}\n${lines.join('\n')}`;
            })
            .join('\n\n');
    }

    /**
     * The async clipboard API is unavailable over plain HTTP (e.g. opening the
     * dashboard from a phone on the LAN), so fall back to a hidden textarea.
     */
    async function writeToClipboard(text) {
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(text);
                return true;
            }
        } catch (error) {
            console.warn('Clipboard API unavailable, falling back:', error);
        }

        const scratch = document.createElement('textarea');
        scratch.value = text;
        scratch.setAttribute('readonly', '');
        scratch.style.position = 'fixed';
        scratch.style.opacity = '0';
        document.body.appendChild(scratch);
        scratch.select();
        let copied = false;
        try {
            copied = document.execCommand('copy');
        } catch (error) {
            console.error('Clipboard fallback failed:', error);
        }
        document.body.removeChild(scratch);
        return copied;
    }

    async function copyShoppingList(onlyPart, button) {
        const text = shoppingListText(onlyPart);
        if (!text) return;

        const fallback = document.getElementById('parts-copy-fallback');
        const fallbackText = document.getElementById('parts-copy-text');
        const original = button.textContent;

        if (await writeToClipboard(text)) {
            button.textContent = 'Copied';
            fallback.classList.add('hidden');
        } else {
            button.textContent = 'Copy blocked';
            fallbackText.value = text;
            fallback.classList.remove('hidden');
            fallbackText.focus();
            fallbackText.select();
        }
        setTimeout(() => { button.textContent = original; }, 1200);
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
        renderIncomingPartsCard(item.id);
    }

    async function renderIncomingPartsCard(itemId) {
        const card = document.getElementById('modal-incoming-parts-card');
        const container = document.getElementById('modal-incoming-parts');
        card.classList.add('hidden');
        container.innerHTML = '';
        try {
            const res = await fetch(`/api/inventory/${itemId}/incoming-parts`);
            const parts = await res.json();
            if (!Array.isArray(parts) || parts.length === 0) return;
            const statusLabel = { paid: 'ordered', shipped: 'shipped', received: 'received' };
            container.innerHTML = parts.map((p) => `
                <div class="flex items-start justify-between gap-2">
                    <span>${escapeHtml(p.sku_text || p.item_title)}${p.qty > 1 ? ` ×${p.qty}` : ''}</span>
                    <span class="text-xs font-semibold whitespace-nowrap ${p.order_status === 'received' ? 'text-green-700' : 'text-blue-700'}">
                        ${escapeHtml(statusLabel[p.order_status] || p.order_status || '')}${p.tracking_no ? ` · ${escapeHtml(p.tracking_no)}` : ''}
                    </span>
                </div>
            `).join('');
            card.classList.remove('hidden');
        } catch (error) {
            console.error('Failed to load incoming parts:', error);
        }
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
            elements.title.innerText = result.item.model || `Device #${currentItemId}`;
            renderTable();
            renderPartsSummary();
            renderShipmentPicker();
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
            renderTable();
            renderPartsSummary();
            renderShipmentPicker();
            closeModal();
        } catch (error) {
            console.error('Delete error:', error);
            alert(error.message || 'Failed to delete device');
        } finally {
            elements.btnDelete.disabled = false;
            elements.btnDelete.textContent = 'Delete Device';
        }
    }

    // ---- Shipments tab ----

    const shipmentPicker = document.getElementById('shipment-picker');
    const shipmentSearch = document.getElementById('shipment-search');
    const shipmentTracking = document.getElementById('shipment-tracking');
    const btnCreateShipment = document.getElementById('btn-create-shipment');
    const shipmentSelectedCount = document.getElementById('shipment-selected-count');
    const shipmentStatus = document.getElementById('shipment-status');
    const shipmentsList = document.getElementById('shipments-list');
    const printShipmentRoot = document.getElementById('print-shipment');

    let shipmentsData = [];
    const shipmentSelectedIds = new Set();

    function formatTimestamp(value) {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return date.toLocaleString();
    }

    function showShipmentStatus(message, isError = false) {
        shipmentStatus.classList.remove('hidden');
        shipmentStatus.textContent = message;
        shipmentStatus.classList.toggle('text-red-600', isError);
        shipmentStatus.classList.toggle('text-gray-500', !isError);
    }

    function updateCreateShipmentButton() {
        const hasTracking = Boolean(shipmentTracking.value.trim());
        btnCreateShipment.disabled = !(hasTracking && shipmentSelectedIds.size > 0);
        const n = shipmentSelectedIds.size;
        shipmentSelectedCount.textContent = `${n} selected`;
    }

    function renderShipmentPicker() {
        const query = shipmentSearch.value;
        const inStorage = inventoryData.filter(isInStorage);
        const items = inStorage.filter((item) => matchesSearch(item, query));

        if (inStorage.length === 0) {
            shipmentPicker.innerHTML = `<div class="px-4 py-6 text-center text-sm text-gray-500">No devices in storage to ship.</div>`;
            updateCreateShipmentButton();
            return;
        }

        if (items.length === 0) {
            shipmentPicker.innerHTML = `<div class="px-4 py-6 text-center text-sm text-gray-500">No in-storage devices match "${escapeHtml(query.trim())}".</div>`;
            updateCreateShipmentButton();
            return;
        }

        shipmentPicker.innerHTML = items.map((item) => {
            const checked = shipmentSelectedIds.has(item.id) ? 'checked' : '';
            return `
                <label class="flex items-start gap-3 px-4 py-3 hover:bg-gray-50 cursor-pointer">
                    <input type="checkbox" class="shipment-pick mt-1 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        data-id="${item.id}" ${checked}>
                    <span class="min-w-0">
                        <span class="block text-sm font-medium text-gray-900">#${item.id} · ${escapeHtml(item.model || 'Unknown')}</span>
                        <span class="block text-xs text-gray-500">
                            ${item.inventory_number ? 'Inv #' + escapeHtml(item.inventory_number) + ' · ' : ''}
                            ${escapeHtml(item.serial_number || 'No serial')} · ${escapeHtml(item.imei || 'No IMEI')}
                        </span>
                    </span>
                </label>
            `;
        }).join('');
        updateCreateShipmentButton();
    }

    async function loadShipments() {
        try {
            const res = await fetch('/api/shipments');
            shipmentsData = await res.json();
            renderShipments();
        } catch (error) {
            console.error('Error fetching shipments:', error);
            shipmentsList.innerHTML = `<div class="bg-white shadow rounded-lg p-6 text-center text-sm text-red-500">Failed to load shipments.</div>`;
        }
    }

    function renderShipments() {
        if (!shipmentsData.length) {
            shipmentsList.innerHTML = `<div class="bg-white shadow rounded-lg p-6 text-center text-sm text-gray-500">No shipments yet.</div>`;
            return;
        }

        shipmentsList.innerHTML = shipmentsData.map((shipment) => {
            const inTransit = shipment.status === 'in_transit';
            const statusClass = inTransit
                ? 'bg-sky-100 text-sky-800'
                : 'bg-gray-200 text-gray-700';
            const statusLabel = inTransit ? 'In Transit' : 'Received';
            const dateLabel = inTransit
                ? `Created ${escapeHtml(formatTimestamp(shipment.created_at))}`
                : `Received ${escapeHtml(formatTimestamp(shipment.received_at || shipment.created_at))}`;
            const actions = inTransit
                ? `
                    <button type="button" class="btn-print-shipment border border-gray-300 hover:bg-gray-50 text-gray-700 text-sm font-medium px-3 py-1.5 rounded-lg" data-id="${shipment.id}">Print list</button>
                    <button type="button" class="btn-receive-shipment bg-green-600 hover:bg-green-700 text-white text-sm font-medium px-3 py-1.5 rounded-lg" data-id="${shipment.id}">Confirm received</button>
                    <button type="button" class="btn-cancel-shipment border border-red-200 hover:bg-red-50 text-red-700 text-sm font-medium px-3 py-1.5 rounded-lg" data-id="${shipment.id}">Cancel shipment</button>
                `
                : `
                    <button type="button" class="btn-print-shipment border border-gray-300 hover:bg-gray-50 text-gray-700 text-sm font-medium px-3 py-1.5 rounded-lg" data-id="${shipment.id}">Print list</button>
                `;

            const rows = (shipment.items || []).map((item) => `
                <tr class="border-t border-gray-100">
                    <td class="px-3 py-2 text-sm text-gray-500">#${item.id}</td>
                    <td class="px-3 py-2 text-sm text-gray-900">${escapeHtml(item.model || 'Unknown')}</td>
                    <td class="px-3 py-2 text-xs text-gray-500">${escapeHtml(item.serial_number || 'N/A')}<br>${escapeHtml(item.imei || 'N/A')}</td>
                    <td class="px-3 py-2 text-right">
                        ${inTransit
                            ? `<button type="button" class="btn-remove-shipment-item text-xs text-red-600 hover:text-red-800" data-id="${shipment.id}" data-item="${item.id}">Remove</button>`
                            : ''}
                    </td>
                </tr>
            `).join('');

            return `
                <div class="bg-white shadow rounded-lg overflow-hidden" data-shipment="${shipment.id}">
                    <div class="px-4 py-3 bg-gray-50 border-b border-gray-200 flex flex-wrap items-center gap-3">
                        <span class="text-sm font-semibold text-gray-800">${escapeHtml(shipment.tracking_number)}</span>
                        <span class="px-2 py-0.5 rounded-full text-xs font-semibold ${statusClass}">${statusLabel}</span>
                        <span class="text-xs text-gray-500">${shipment.item_count || (shipment.items || []).length} item${(shipment.item_count || (shipment.items || []).length) === 1 ? '' : 's'}</span>
                        <span class="text-xs text-gray-400">${dateLabel}</span>
                        <div class="ml-auto flex flex-wrap gap-2">${actions}</div>
                    </div>
                    <div class="overflow-x-auto">
                        <table class="min-w-full">
                            <thead>
                                <tr class="text-left text-xs font-medium text-gray-500 uppercase">
                                    <th class="px-3 py-2">ID</th>
                                    <th class="px-3 py-2">Model</th>
                                    <th class="px-3 py-2">Serial / IMEI</th>
                                    <th class="px-3 py-2"></th>
                                </tr>
                            </thead>
                            <tbody>${rows || `<tr><td colspan="4" class="px-3 py-4 text-sm text-gray-500">No devices.</td></tr>`}</tbody>
                        </table>
                    </div>
                </div>
            `;
        }).join('');
    }

    async function refreshAfterShipmentChange() {
        await Promise.all([loadInventory(), loadShipments()]);
    }

    async function createShipment() {
        const tracking_number = shipmentTracking.value.trim();
        const inventory_ids = Array.from(shipmentSelectedIds);
        if (!tracking_number || inventory_ids.length === 0) return;

        btnCreateShipment.disabled = true;
        btnCreateShipment.textContent = 'Creating...';
        try {
            const res = await fetch('/api/shipments', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tracking_number, inventory_ids }),
            });
            const result = await res.json();
            if (!res.ok) throw new Error(result.message || 'Create failed');
            shipmentSelectedIds.clear();
            shipmentTracking.value = '';
            shipmentSearch.value = '';
            showShipmentStatus(`Created shipment ${result.shipment.tracking_number} with ${result.shipment.item_count} item${result.shipment.item_count === 1 ? '' : 's'}.`);
            await refreshAfterShipmentChange();
        } catch (error) {
            showShipmentStatus(error.message || 'Failed to create shipment', true);
        } finally {
            btnCreateShipment.textContent = 'Create shipment';
            updateCreateShipmentButton();
        }
    }

    async function cancelShipment(shipmentId) {
        const shipment = shipmentsData.find((s) => s.id === shipmentId);
        const label = shipment ? shipment.tracking_number : `#${shipmentId}`;
        if (!confirm(`Cancel shipment ${label}? Devices will return to In Storage.`)) return;
        try {
            const res = await fetch(`/api/shipments/${shipmentId}`, { method: 'DELETE' });
            const result = await res.json();
            if (!res.ok) throw new Error(result.message || 'Cancel failed');
            showShipmentStatus(`Cancelled ${label}.`);
            await refreshAfterShipmentChange();
        } catch (error) {
            showShipmentStatus(error.message || 'Failed to cancel shipment', true);
        }
    }

    async function receiveShipment(shipmentId) {
        const shipment = shipmentsData.find((s) => s.id === shipmentId);
        const label = shipment ? shipment.tracking_number : `#${shipmentId}`;
        if (!confirm(`Confirm ${label} received? Devices will be archived.`)) return;
        try {
            const res = await fetch(`/api/shipments/${shipmentId}/receive`, { method: 'POST' });
            const result = await res.json();
            if (!res.ok) throw new Error(result.message || 'Update failed');
            showShipmentStatus(`Marked ${label} received.`);
            await refreshAfterShipmentChange();
        } catch (error) {
            showShipmentStatus(error.message || 'Failed to confirm received', true);
        }
    }

    async function removeShipmentItem(shipmentId, inventoryId) {
        try {
            const res = await fetch(`/api/shipments/${shipmentId}/items/${inventoryId}`, { method: 'DELETE' });
            const result = await res.json();
            if (!res.ok) throw new Error(result.message || 'Remove failed');
            showShipmentStatus(result.deleted ? 'Shipment removed (no items left).' : `Removed device #${inventoryId}.`);
            await refreshAfterShipmentChange();
        } catch (error) {
            showShipmentStatus(error.message || 'Failed to remove device', true);
        }
    }

    function printShipment(shipment) {
        const items = shipment.items || [];
        const rows = items.map((item) => `
            <tr>
                <td>${item.id}</td>
                <td>${escapeHtml(item.inventory_number || '')}</td>
                <td>${escapeHtml(item.model || '')}</td>
                <td>${escapeHtml(item.color || '')}</td>
                <td>${escapeHtml(item.capacity || '')}</td>
                <td>${escapeHtml(item.serial_number || '')}</td>
                <td>${escapeHtml(item.imei || '')}</td>
                <td>${escapeHtml(item.lock_status || '')}</td>
                <td>${escapeHtml(item.damage_condition || '')}</td>
            </tr>
        `).join('');

        printShipmentRoot.innerHTML = `
            <h1 style="font-size: 22px; font-weight: 700; margin: 0 0 8px;">Shipment inventory list</h1>
            <p style="margin: 0 0 4px;"><strong>Tracking:</strong> ${escapeHtml(shipment.tracking_number || '')}</p>
            <p style="margin: 0 0 4px;"><strong>Date:</strong> ${escapeHtml(formatTimestamp(shipment.created_at))}</p>
            <p style="margin: 0 0 16px;"><strong>Items:</strong> ${items.length}</p>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Inv #</th>
                        <th>Model</th>
                        <th>Color</th>
                        <th>Capacity</th>
                        <th>Serial</th>
                        <th>IMEI</th>
                        <th>Lock</th>
                        <th>Condition</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows || '<tr><td colspan="9">No devices.</td></tr>'}
                </tbody>
            </table>
        `;
        window.print();
    }

    window.addEventListener('afterprint', () => {
        printShipmentRoot.innerHTML = '';
    });

    // ---- Purchases tab ----

    const purchasesList = document.getElementById('purchases-list');
    const purchaseFilesInput = document.getElementById('purchase-files');
    const btnImportPurchases = document.getElementById('btn-import-purchases');
    const btnClassifyPurchases = document.getElementById('btn-classify-purchases');
    const purchaseFilter = document.getElementById('purchase-filter');
    const purchaseStatus = document.getElementById('purchase-status');
    const llmSettingsCard = document.getElementById('llm-settings-card');
    const llmBaseUrl = document.getElementById('llm-base-url');
    const llmModel = document.getElementById('llm-model');
    const llmApiKey = document.getElementById('llm-api-key');
    const llmSettingsStatus = document.getElementById('llm-settings-status');

    let purchasesData = { items: [], categories: [], part_types: [] };
    let llmSettingsLoaded = false;

    const ORDER_STATUS_STYLE = {
        paid: 'bg-yellow-100 text-yellow-800',
        shipped: 'bg-blue-100 text-blue-800',
        received: 'bg-green-100 text-green-800',
    };
    const CATEGORY_STYLE = {
        part: 'bg-green-100 text-green-800',
        service: 'bg-purple-100 text-purple-800',
        tool: 'bg-orange-100 text-orange-800',
        accessory: 'bg-blue-100 text-blue-800',
        personal: 'bg-gray-200 text-gray-700',
        unknown: 'bg-gray-100 text-gray-500',
    };

    function showPurchaseStatus(message, isError = false) {
        purchaseStatus.classList.remove('hidden');
        purchaseStatus.textContent = message;
        purchaseStatus.classList.toggle('text-red-600', isError);
        purchaseStatus.classList.toggle('text-gray-500', !isError);
    }

    async function loadPurchases() {
        try {
            const filter = purchaseFilter.value;
            const url = filter ? `/api/purchases?review_status=${filter}` : '/api/purchases';
            const res = await fetch(url);
            purchasesData = await res.json();
            renderPurchases();
        } catch (error) {
            console.error('Error fetching purchases:', error);
            purchasesList.innerHTML = `<div class="bg-white shadow rounded-lg p-6 text-center text-sm text-red-500">Failed to load purchases.</div>`;
        }
    }

    function renderPurchases() {
        const items = purchasesData.items || [];
        if (items.length === 0) {
            purchasesList.innerHTML = `<div class="bg-white shadow rounded-lg p-6 text-center text-sm text-gray-500">No purchases${purchaseFilter.value ? ' with this status' : ' imported yet. Upload the Taobao xlsx exports above'}.</div>`;
            return;
        }

        const orders = new Map();
        items.forEach((item) => {
            if (!orders.has(item.order_no)) {
                orders.set(item.order_no, { meta: item, items: [] });
            }
            orders.get(item.order_no).items.push(item);
        });

        purchasesList.innerHTML = Array.from(orders.values()).map(({ meta, items: orderItems }) => {
            const statusClass = ORDER_STATUS_STYLE[meta.order_status] || 'bg-gray-100 text-gray-600';
            const logistics = meta.tracking_no
                ? `<span class="text-xs text-gray-500">${escapeHtml(meta.logistics_company || '')} ${escapeHtml(meta.tracking_no)}</span>`
                : '';
            return `
                <div class="bg-white shadow rounded-lg overflow-hidden">
                    <div class="px-4 py-3 bg-gray-50 border-b border-gray-200 flex flex-wrap items-center gap-3">
                        <span class="text-sm font-semibold text-gray-800">${escapeHtml(meta.shop_name || 'Unknown shop')}</span>
                        <span class="px-2 py-0.5 rounded-full text-xs font-semibold ${statusClass}">${escapeHtml(meta.order_status || '')}</span>
                        ${logistics}
                        <span class="ml-auto text-xs text-gray-400">${escapeHtml(meta.submit_time || '')} · #${escapeHtml(meta.order_no)}</span>
                    </div>
                    <div class="divide-y divide-gray-100">
                        ${orderItems.map(renderPurchaseItem).join('')}
                    </div>
                </div>
            `;
        }).join('');
    }

    function renderPurchaseItem(item) {
        const categories = purchasesData.categories || [];
        const partTypes = purchasesData.part_types || [];
        const isPart = item.category === 'part';
        const catClass = CATEGORY_STYLE[item.category] || CATEGORY_STYLE.unknown;
        const dimmed = item.review_status === 'dismissed' ? 'opacity-50' : '';

        const categoryOptions = categories.map((c) =>
            `<option value="${escapeAttr(c)}" ${c === item.category ? 'selected' : ''}>${escapeHtml(c)}</option>`).join('');
        const partTypeOptions = ['<option value="">—</option>'].concat(partTypes.map((p) =>
            `<option value="${escapeAttr(p)}" ${p === item.part_type ? 'selected' : ''}>${escapeHtml(p)}</option>`)).join('');

        const confidence = item.confidence != null && item.classified_by === 'llm'
            ? `<span class="text-xs ${item.confidence >= 0.8 ? 'text-green-600' : 'text-orange-500'}">LLM ${Math.round(item.confidence * 100)}%</span>`
            : (item.classified_by === 'manual' ? '<span class="text-xs text-blue-500">manual</span>' : '');

        const links = (item.links || []).map((link) => `
            <span class="inline-flex items-center gap-1 bg-green-50 border border-green-200 text-green-800 text-xs px-2 py-1 rounded-full">
                Linked: #${link.inventory_id} ${escapeHtml(link.model || '')}${link.qty > 1 ? ` ×${link.qty}` : ''}
                <button type="button" class="btn-unlink text-green-600 hover:text-red-600 font-bold" data-item="${item.id}" data-link="${link.link_id}" title="Remove link">×</button>
            </span>
        `).join('');

        const suggestions = (item.suggestions || []).map((s) => `
            <button type="button" class="btn-link-device inline-flex items-center gap-1 bg-blue-50 border border-blue-200 text-blue-800 hover:bg-blue-100 text-xs px-2 py-1 rounded-full"
                data-item="${item.id}" data-device="${s.inventory_id}">
                + Link #${s.inventory_id} ${escapeHtml(s.model || '')}${s.inventory_number ? ` (Inv ${escapeHtml(s.inventory_number)})` : ''} — ${escapeHtml(s.part_name)}
            </button>
        `).join('');

        const reviewButtons = `
            <div class="flex gap-1">
                ${item.review_status !== 'confirmed'
                    ? `<button type="button" class="btn-review text-xs px-2 py-1 rounded border border-green-300 text-green-700 hover:bg-green-50" data-item="${item.id}" data-status="confirmed">Confirm</button>`
                    : `<button type="button" class="btn-review text-xs px-2 py-1 rounded bg-green-600 text-white" data-item="${item.id}" data-status="pending">Confirmed ✓</button>`}
                ${item.review_status !== 'dismissed'
                    ? `<button type="button" class="btn-review text-xs px-2 py-1 rounded border border-gray-300 text-gray-500 hover:bg-gray-50" data-item="${item.id}" data-status="dismissed">Dismiss</button>`
                    : `<button type="button" class="btn-review text-xs px-2 py-1 rounded bg-gray-500 text-white" data-item="${item.id}" data-status="pending">Dismissed ↩</button>`}
            </div>
        `;

        return `
            <div class="px-4 py-3 ${dimmed}" data-item-row="${item.id}">
                <div class="flex flex-wrap items-start gap-3">
                    <div class="flex-1 min-w-[16rem]">
                        <div class="text-sm text-gray-800">${escapeHtml(item.item_title)}</div>
                        <div class="text-xs text-gray-500 mt-0.5">${escapeHtml(item.sku_text || '')}</div>
                        <div class="text-xs text-gray-400 mt-0.5">×${item.quantity}${item.unit_price != null ? ` · ¥${item.unit_price}` : ''}</div>
                    </div>
                    <div class="flex flex-wrap items-center gap-2">
                        <span class="px-2 py-0.5 rounded-full text-xs font-semibold ${catClass}">${escapeHtml(item.category)}</span>
                        ${confidence}
                        <select class="sel-category border border-gray-300 rounded px-2 py-1 text-xs bg-white" data-item="${item.id}">${categoryOptions}</select>
                        <select class="sel-part-type border border-gray-300 rounded px-2 py-1 text-xs bg-white ${isPart ? '' : 'hidden'}" data-item="${item.id}">${partTypeOptions}</select>
                        <input type="text" class="inp-models border border-gray-300 rounded px-2 py-1 text-xs w-40 ${isPart ? '' : 'hidden'}" data-item="${item.id}"
                            value="${escapeAttr((item.models || []).join(', '))}" placeholder="Models, e.g. iPhone 11">
                        ${reviewButtons}
                    </div>
                </div>
                ${item.notes ? `<div class="text-xs text-gray-400 italic mt-1">${escapeHtml(item.notes)}</div>` : ''}
                ${(links || suggestions) ? `<div class="flex flex-wrap gap-2 mt-2">${links}${suggestions}</div>` : ''}
            </div>
        `;
    }

    async function patchPurchaseItem(itemId, payload) {
        const res = await fetch(`/api/purchases/items/${itemId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.message || 'Update failed');
        await loadPurchases();
    }

    async function importPurchases() {
        const files = purchaseFilesInput.files;
        if (!files || files.length === 0) {
            showPurchaseStatus('Choose one or more .xlsx files first.', true);
            return;
        }
        const formData = new FormData();
        Array.from(files).forEach((f) => formData.append('files', f));

        btnImportPurchases.disabled = true;
        btnImportPurchases.textContent = 'Importing...';
        try {
            const res = await fetch('/api/purchases/import', { method: 'POST', body: formData });
            const result = await res.json();
            const parts = (result.files || []).map((f) => f.success
                ? `${f.filename}: ${f.items_new} new, ${f.items_skipped} existing, ${f.orders_updated} orders updated`
                : `${f.filename}: FAILED (${f.message})`);
            showPurchaseStatus(parts.join(' | '), !result.success);
            purchaseFilesInput.value = '';
            await loadPurchases();
        } catch (error) {
            showPurchaseStatus(error.message || 'Import failed', true);
        } finally {
            btnImportPurchases.disabled = false;
            btnImportPurchases.textContent = 'Import';
        }
    }

    async function classifyPurchases() {
        btnClassifyPurchases.disabled = true;
        btnClassifyPurchases.textContent = 'Classifying...';
        try {
            const res = await fetch('/api/purchases/classify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}),
            });
            const result = await res.json();
            if (result.error) {
                showPurchaseStatus(`Classified ${result.from_llm + result.from_cache}/${result.total} — ${result.error}`, true);
            } else if (result.total === 0) {
                showPurchaseStatus('Nothing to classify — all items already have a category.');
            } else {
                showPurchaseStatus(`Classified ${result.total} item${result.total === 1 ? '' : 's'} (${result.from_llm} via LLM, ${result.from_cache} from cache).`);
            }
            await loadPurchases();
        } catch (error) {
            showPurchaseStatus(error.message || 'Classification failed', true);
        } finally {
            btnClassifyPurchases.disabled = false;
            btnClassifyPurchases.textContent = 'Classify with LLM';
        }
    }

    async function loadLlmSettings() {
        if (llmSettingsLoaded) return;
        try {
            const res = await fetch('/api/settings/llm');
            const settings = await res.json();
            llmBaseUrl.value = settings.llm_base_url || '';
            llmModel.value = settings.llm_model || '';
            llmApiKey.placeholder = settings.llm_api_key_set ? '••••••••  (saved — type to replace)' : 'sk-...';
            llmSettingsLoaded = true;
        } catch (error) {
            llmSettingsStatus.textContent = 'Failed to load settings';
        }
    }

    async function saveLlmSettings() {
        llmSettingsStatus.textContent = 'Saving...';
        try {
            const payload = {
                llm_base_url: llmBaseUrl.value.trim(),
                llm_model: llmModel.value.trim(),
            };
            if (llmApiKey.value.trim()) payload.llm_api_key = llmApiKey.value.trim();
            const res = await fetch('/api/settings/llm', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await res.json();
            if (!res.ok) throw new Error(result.message || 'Save failed');
            llmApiKey.value = '';
            llmSettingsLoaded = false;
            await loadLlmSettings();
            llmSettingsStatus.textContent = result.configured ? 'Saved — configured.' : 'Saved, but base URL/model still missing.';
        } catch (error) {
            llmSettingsStatus.textContent = error.message || 'Save failed';
        }
    }

    async function testLlmSettings() {
        llmSettingsStatus.textContent = 'Testing...';
        try {
            const res = await fetch('/api/settings/llm/test', { method: 'POST' });
            const result = await res.json();
            llmSettingsStatus.textContent = result.message || (result.success ? 'OK' : 'Failed');
        } catch (error) {
            llmSettingsStatus.textContent = error.message || 'Test failed';
        }
    }

    purchasesList.addEventListener('change', async (e) => {
        const itemId = parseInt(e.target.dataset.item, 10);
        if (Number.isNaN(itemId)) return;
        try {
            if (e.target.classList.contains('sel-category')) {
                await patchPurchaseItem(itemId, { category: e.target.value });
            } else if (e.target.classList.contains('sel-part-type')) {
                await patchPurchaseItem(itemId, { part_type: e.target.value || null });
            } else if (e.target.classList.contains('inp-models')) {
                await patchPurchaseItem(itemId, { models: e.target.value });
            }
        } catch (error) {
            showPurchaseStatus(error.message, true);
        }
    });

    purchasesList.addEventListener('click', async (e) => {
        const reviewBtn = e.target.closest('.btn-review');
        const linkBtn = e.target.closest('.btn-link-device');
        const unlinkBtn = e.target.closest('.btn-unlink');
        try {
            if (reviewBtn) {
                await patchPurchaseItem(parseInt(reviewBtn.dataset.item, 10), { review_status: reviewBtn.dataset.status });
            } else if (linkBtn) {
                const res = await fetch(`/api/purchases/items/${linkBtn.dataset.item}/links`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ inventory_id: parseInt(linkBtn.dataset.device, 10), qty: 1 }),
                });
                const result = await res.json();
                if (!res.ok) throw new Error(result.message || 'Link failed');
                await Promise.all([loadPurchases(), loadInventory()]);
            } else if (unlinkBtn) {
                const res = await fetch(`/api/purchases/items/${unlinkBtn.dataset.item}/links/${unlinkBtn.dataset.link}`, { method: 'DELETE' });
                const result = await res.json();
                if (!res.ok) throw new Error(result.message || 'Unlink failed');
                await Promise.all([loadPurchases(), loadInventory()]);
            }
        } catch (error) {
            showPurchaseStatus(error.message, true);
        }
    });

    btnImportPurchases.addEventListener('click', importPurchases);
    btnClassifyPurchases.addEventListener('click', classifyPurchases);
    purchaseFilter.addEventListener('change', loadPurchases);
    document.getElementById('btn-toggle-llm-settings').addEventListener('click', () => {
        llmSettingsCard.classList.toggle('hidden');
        if (!llmSettingsCard.classList.contains('hidden')) loadLlmSettings();
    });
    document.getElementById('btn-save-llm').addEventListener('click', saveLlmSettings);
    document.getElementById('btn-test-llm').addEventListener('click', testLlmSettings);

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
    tabShipments.addEventListener('click', () => setActiveTab('shipments'));
    tabParts.addEventListener('click', () => setActiveTab('parts'));
    tabPurchases.addEventListener('click', () => setActiveTab('purchases'));
    searchInput.addEventListener('input', renderTable);
    sortSelect.addEventListener('change', renderTable);
    showArchived.addEventListener('change', renderTable);
    shipmentSearch.addEventListener('input', renderShipmentPicker);
    shipmentTracking.addEventListener('input', updateCreateShipmentButton);
    btnCreateShipment.addEventListener('click', createShipment);
    shipmentPicker.addEventListener('change', (e) => {
        const box = e.target.closest('.shipment-pick');
        if (!box) return;
        const id = parseInt(box.dataset.id, 10);
        if (Number.isNaN(id)) return;
        if (box.checked) shipmentSelectedIds.add(id);
        else shipmentSelectedIds.delete(id);
        updateCreateShipmentButton();
    });
    shipmentsList.addEventListener('click', (e) => {
        const printBtn = e.target.closest('.btn-print-shipment');
        const receiveBtn = e.target.closest('.btn-receive-shipment');
        const cancelBtn = e.target.closest('.btn-cancel-shipment');
        const removeBtn = e.target.closest('.btn-remove-shipment-item');
        if (printBtn) {
            const shipment = shipmentsData.find((s) => s.id === parseInt(printBtn.dataset.id, 10));
            if (shipment) printShipment(shipment);
        } else if (receiveBtn) {
            receiveShipment(parseInt(receiveBtn.dataset.id, 10));
        } else if (cancelBtn) {
            cancelShipment(parseInt(cancelBtn.dataset.id, 10));
        } else if (removeBtn) {
            removeShipmentItem(parseInt(removeBtn.dataset.id, 10), parseInt(removeBtn.dataset.item, 10));
        }
    });
    partsHideOrdered.addEventListener('change', renderPartsSummary);
    document.getElementById('btn-copy-parts').addEventListener('click', (e) => {
        copyShoppingList(null, e.currentTarget);
    });
    partsSummaryList.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-copy-part');
        if (btn) copyShoppingList(btn.dataset.part, btn);
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
