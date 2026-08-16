document.addEventListener('DOMContentLoaded', () => {
    const tableBody = document.getElementById('inventory-body');
    const modal = document.getElementById('detail-modal');
    
    // Elements inside modal
    const elements = {
        modelName: document.getElementById('modal-model-name'),
        color: document.getElementById('modal-color'),
        capacity: document.getElementById('modal-capacity'),
        battery: document.getElementById('modal-battery'),
        ios: document.getElementById('modal-ios'),
        serial: document.getElementById('modal-serial'),
        imei: document.getElementById('modal-imei'),
        date: document.getElementById('modal-date'),
        visionType: document.getElementById('modal-vision-type'),
        remarks: document.getElementById('modal-remarks'),
        condition: document.getElementById('modal-condition'),
        partsList: document.getElementById('modal-parts-list'),
        imgFront: document.getElementById('modal-img-front'),
        imgFrontPh: document.getElementById('modal-img-front-ph'),
        imgBack: document.getElementById('modal-img-back'),
        imgBackPh: document.getElementById('modal-img-back-ph')
    };

    let inventoryData = [];

    // Fetch inventory
    async function loadInventory() {
        try {
            const res = await fetch('/api/inventory');
            inventoryData = await res.json();
            renderTable();
        } catch (error) {
            console.error('Error fetching inventory:', error);
            tableBody.innerHTML = `<tr><td colspan="5" class="px-6 py-4 text-center text-sm text-red-500">Failed to load inventory.</td></tr>`;
        }
    }

    function renderTable() {
        if (inventoryData.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="5" class="px-6 py-4 text-center text-sm text-gray-500">No devices in inventory yet.</td></tr>`;
            return;
        }

        tableBody.innerHTML = inventoryData.map(item => {
            let parts = [];
            try { parts = JSON.parse(item.parts_needed || '[]'); } catch(e){}
            const partsStr = parts.length > 0 ? parts.join(', ') : 'None';

            return `
                <tr class="table-row-hover" data-id="${item.id}">
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        #${item.id}<br><span class="text-xs text-gray-400">${item.date_received || ''}</span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <div class="text-sm font-medium text-gray-900">${item.model || 'Unknown'}</div>
                        <div class="text-sm text-gray-500">${item.color || ''} ${item.capacity || ''} ${item.vision_device_type ? '· ' + item.vision_device_type : ''}</div>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        S/N: ${item.serial_number || 'N/A'}<br>
                        IMEI: ${item.imei || 'N/A'}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full bg-yellow-100 text-yellow-800">
                            ${item.damage_condition || 'Unknown'}
                        </span>
                    </td>
                    <td class="px-6 py-4 text-sm text-gray-500 truncate max-w-xs">
                        ${partsStr}
                    </td>
                </tr>
            `;
        }).join('');

        // Attach click events
        document.querySelectorAll('.table-row-hover').forEach(row => {
            row.addEventListener('click', () => {
                const id = parseInt(row.getAttribute('data-id'));
                const item = inventoryData.find(i => i.id === id);
                if (item) openModal(item);
            });
        });
    }

    function openModal(item) {
        elements.modelName.innerText = item.model || 'Unknown Device';
        elements.color.innerText = item.color || '-';
        elements.capacity.innerText = item.capacity || '-';
        elements.battery.innerText = item.battery_health || '-';
        elements.ios.innerText = item.ios_version || '-';
        elements.serial.innerText = item.serial_number || '-';
        elements.imei.innerText = item.imei || '-';
        elements.date.innerText = item.date_received || '-';
        elements.visionType.innerText = item.vision_device_type || '-';
        elements.remarks.innerText = item.remarks || 'No remarks provided.';
        elements.condition.innerText = item.damage_condition || 'Unknown';

        // Parts needed
        let parts = [];
        try { parts = JSON.parse(item.parts_needed || '[]'); } catch(e){}
        if (parts.length > 0) {
            elements.partsList.innerHTML = parts.map(p => `
                <li class="flex items-start">
                    <svg class="h-5 w-5 text-green-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                    </svg>
                    <span class="text-sm text-gray-700">${p}</span>
                </li>
            `).join('');
        } else {
            elements.partsList.innerHTML = `<li class="text-sm text-gray-500 italic">No parts required.</li>`;
        }

        // Images
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
    }

    document.getElementById('btn-close-modal').addEventListener('click', closeModal);
    document.getElementById('btn-close-modal-bottom').addEventListener('click', closeModal);
    document.getElementById('modal-overlay').addEventListener('click', closeModal);

    // Initial load
    loadInventory();
});
