

function parseData(browserData) {
	var groups = {};

	for (browser of Object.values(browserData)) {
		if (browser.browserprofile) {
			continue;
		}
		let groupName = browser.id.split(":")[0];
		// declare new group from name of first browser found
		if (groups[groupName] === undefined) {
			groups[groupName] = {"id": groupName,
								 "label": browser.name,
								 "choices": []}
		}
		let group = groups[groupName];
		group.choices.push({"value": browser.id,
							"label": browser.name + " " + browser.version,
							"customProperties": browser});
	}

	return Object.values(groups);
}

function templateCallback(template) {
	var render = (classNames, data, choice) => {
		let content = "";

		if (choice) {
			content = `<div class="${classNames.item} ${classNames.itemChoice} ${data.disabled ? classNames.itemDisabled : classNames.itemSelectable}" data-select-text="${this.config.itemSelectText}" data-choice ${data.disabled ? 'data-choice-disabled aria-disabled="true"' : 'data-choice-selectable'} data-id="${data.id}" data-value="${data.value}" ${data.groupId > 0 ? 'role="treeitem"' : 'role="option"'}>`;
 		} else {
 			content = `<div class="${classNames.item} ${data.highlighted ? classNames.highlightedState : classNames.itemSelectable}" data-item data-id="${data.id}" data-value="${data.value}" ${data.active ? 'aria-selected="true"' : ''} ${data.disabled ? 'aria-disabled="true"' : ''}>`;
 		}

		if (data.customProperties && data.customProperties.icon) {
			content += `<span class="bicon"><img src="${data.customProperties.icon}"/></span>`;
		} else {
			content += `<span class="bicon"></span>`;
		}

		content += `${data.label}</span></div>`

		return template(content);
	}

	return {
			"choice": (classNames, data) => { return render(classNames, data, true) },
			"item": (classNames, data) =>  {return render(classNames, data, false) }
		   };
}

function init() {
	var fuse = {'minMatchCharLength': 1, 'threshold': 0.1, 'distance': 100};
	var choices = new Choices("#browsers", {"searchFloor": 1,
											"fuseOptions": fuse,
											"position": "bottom",
											"itemSelectText": "",
											"shouldSort": false,
											"searchPlaceholderValue": "Filter Browsers",
											"callbackOnCreateTemplates": templateCallback});

	//placeholder fix
	var placeholderItem = choices._getTemplate("placeholder", "Choose a Browser...");
	choices.itemList.append(placeholderItem);

	fetch("/api/images/browser").then(function(response) {
		return response.json();
	}).then(function(data) {
		choices.setChoices(parseData(data), 'value', 'label', false);

		// set selection if value is set
		var value = document.querySelector("#browsers").getAttribute("data-init-value");
		if (value) {
			choices.setChoiceByValue(value);
		}
	});
}

document.addEventListener("DOMContentLoaded", init);

function go(event) {
	event.preventDefault();
	var path = document.querySelector("#browsers").value + "/" + document.querySelector("#url").value;
	document.querySelector("iframe").src = "/view/" + path;
	window.history.replaceState({}, path, "/view-controls/" + path);

	document.querySelector(".browserchooser").classList.add("pure-u-1-5");
	document.querySelector(".browserchooser").classList.remove("pure-u-2-5");
	document.querySelector(".browserpad").classList.remove("pure-u-1-5");
	return false;
}
