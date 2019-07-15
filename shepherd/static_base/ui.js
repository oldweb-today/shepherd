

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
		} else if (data.customProperties && data.customProperties.id) {
			content += `<span class="bicon"><img src="/api/images/browser/${data.customProperties.id}/icon"/></span>`;
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

    window.choices = choices;
    loadChoices(true);

    if (window.timestamp !== undefined) {
        flatpickr("#datetime", {
            enableTime: true,
            dateFormat: "Y-m-d H:i:S",
            enableSeconds: true,
            allowInput: true,
            defaultDate: tsToDate(window.timestamp)
        });
    }
}

function loadChoices(setValue) {
	fetch("/api/images/browser").then(function(response) {
		return response.json();
	}).then(function(data) {
        choices.clearChoices();
		choices.setChoices(parseData(data), 'value', 'label', false);

        if (setValue) {
          // set selection if value is set
          var value = document.querySelector("#browsers").getAttribute("data-init-value");
          if (value) {
              choices.setChoiceByValue(value);
          }
        }
	});
}


function tsToDate(ts) {
  if (ts.length < 14) {
      return new Date();
  }

  var datestr =
    ts.substring(0, 4) +
    '-' +
    ts.substring(4, 6) +
    '-' +
    ts.substring(6, 8) +
    'T' +
    ts.substring(8, 10) +
    ':' +
    ts.substring(10, 12) +
    ':' +
    ts.substring(12, 14) +
    '-00:00';

  return new Date(datestr);
};


document.addEventListener("DOMContentLoaded", init);

function go(event) {
	event.preventDefault();
	var path = document.querySelector("#browsers").value + "/";
    var dt = document.querySelector("#datetime");
    if (dt) {
        path += dt.value.replace(/[^\d]/g, '') + "/";
    }
    path += document.querySelector("#url").value;
	document.querySelector("iframe").src = "/view/" + path;
	window.history.replaceState({}, path, "/browse/" + path);

	document.querySelector(".browserchooser").classList.add("pure-u-1-3");
	document.querySelector(".browserchooser").classList.remove("pure-u-2-3");
	document.querySelector(".browserpad").classList.remove("pure-u-1-3");
	return false;
}
