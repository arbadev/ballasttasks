import { fireEvent, render, screen } from "@testing-library/react";
import { Plus } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { Avatar } from "./Avatar";
import { Button } from "./Button";
import { IconButton } from "./IconButton";
import { Pill } from "./Pill";
import { SegmentedControl } from "./SegmentedControl";
import { Select } from "./Select";
import { TextInput } from "./TextInput";

describe("Button", () => {
  it("is a type=button that fires onClick", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>New task</Button>);
    const button = screen.getByRole("button", { name: "New task" });
    expect(button).toHaveAttribute("type", "button");
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("renders an icon before the label, hidden from assistive tech", () => {
    render(<Button icon={Plus}>New task</Button>);
    const icon = screen.getByRole("button", { name: "New task" }).querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("does not fire when disabled", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick} disabled>Save</Button>);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("has a ghost variant", () => {
    render(<><Button>Primary</Button><Button variant="ghost">Ghost</Button></>);
    expect(screen.getByRole("button", { name: "Ghost" }).className).not.toBe(screen.getByRole("button", { name: "Primary" }).className);
  });
});

describe("IconButton", () => {
  it("takes its accessible name from label", () => {
    const onClick = vi.fn();
    render(<IconButton icon={Plus} label="Open navigation" onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("renders a link when given an href", () => {
    render(<IconButton icon={Plus} label="System status" href="/status" />);
    expect(screen.getByRole("link", { name: "System status" })).toHaveAttribute("href", "/status");
  });
});

describe("Select", () => {
  const options = [{ value: "open", label: "All open" }, { value: "done", label: "Done" }];

  it("labels the native select with its visible prefix", () => {
    render(<Select label="Status" value="open" options={options} onChange={() => {}} />);
    const select = screen.getByRole("combobox", { name: "Status" });
    expect(select).toHaveValue("open");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["All open", "Done"]);
  });

  it("reports the chosen value", () => {
    const onChange = vi.fn();
    render(<Select label="Status" value="open" options={options} onChange={onChange} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "done" } });
    expect(onChange).toHaveBeenCalledWith("done");
  });
});

describe("SegmentedControl", () => {
  const options = [{ value: "list", label: "List", icon: Plus }, { value: "board", label: "Board", icon: Plus }];

  it("is a labelled radio group reflecting the value", () => {
    render(<SegmentedControl label="View" name="view" value="board" options={options} onChange={() => {}} />);
    expect(screen.getByRole("radiogroup", { name: "View" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Board" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "List" })).not.toBeChecked();
  });

  it("reports the chosen option", () => {
    const onChange = vi.fn();
    render(<SegmentedControl label="View" name="view" value="list" options={options} onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Board" }));
    expect(onChange).toHaveBeenCalledWith("board");
  });

  it("slides the thumb to the selected option", () => {
    const { rerender } = render(<SegmentedControl label="View" name="view" value="list" options={options} onChange={() => {}} />);
    const thumb = () => screen.getByRole("radiogroup").querySelector("[data-thumb]") as HTMLElement;
    // Positioned with `left`, as the design does: layout snaps it to the pixel grid, where a
    // transform would leave a blurred edge whenever half the control is a fractional width.
    expect(thumb().style.getPropertyValue("--segment")).toBe("0");
    expect(thumb().style.transform).toBe("");
    rerender(<SegmentedControl label="View" name="view" value="board" options={options} onChange={() => {}} />);
    expect(thumb().style.getPropertyValue("--segment")).toBe("1");
  });
});

describe("form field identity", () => {
  // Chrome's Issues panel flags any form field with neither an id nor a name.
  it("every Select and TextInput renders an id, unique per instance", () => {
    render(
      <>
        <Select label="Status" value="open" options={[{ value: "open", label: "All open" }]} onChange={() => {}} />
        <Select label="Due" value="open" options={[{ value: "open", label: "Any date" }]} onChange={() => {}} />
        <TextInput label="Search tasks" value="" onChange={() => {}} />
      </>,
    );
    const ids = [screen.getByRole("combobox", { name: "Status" }), screen.getByRole("combobox", { name: "Due" }), screen.getByRole("textbox", { name: "Search tasks" })].map((el) => el.id);
    ids.forEach((id) => expect(id).not.toBe(""));
    expect(new Set(ids).size).toBe(3);
  });
});

describe("TextInput", () => {
  it("is labelled, controlled and reports text", () => {
    const onChange = vi.fn();
    render(<TextInput label="Search tasks" placeholder="Search tasks" value="jw" onChange={onChange} icon={Plus} />);
    const input = screen.getByRole("textbox", { name: "Search tasks" });
    expect(input).toHaveValue("jw");
    fireEvent.change(input, { target: { value: "jwt" } });
    expect(onChange).toHaveBeenCalledWith("jwt");
  });

  it("can be a search box", () => {
    render(<TextInput type="search" label="Search tasks" value="" onChange={() => {}} />);
    expect(screen.getByRole("searchbox", { name: "Search tasks" })).toBeInTheDocument();
  });
});

describe("Avatar", () => {
  it("shows initials and names the person", () => {
    render(<Avatar initials="LM" name="Lucía Marín" />);
    expect(screen.getByRole("img", { name: "Lucía Marín" })).toHaveTextContent("LM");
  });

  it("is decorative when the name is already beside it", () => {
    render(<Avatar initials="LM" />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("LM")).toHaveAttribute("aria-hidden", "true");
  });

  it("varies by tone and size", () => {
    render(<><Avatar initials="A" name="a" tone="accent" size={28} /><Avatar initials="B" name="b" /></>);
    expect(screen.getByRole("img", { name: "a" }).className).not.toBe(screen.getByRole("img", { name: "b" }).className);
  });
});

describe("Pill", () => {
  it("renders its content, with tones", () => {
    render(<><Pill>13 tasks</Pill><Pill tone="danger">P0</Pill></>);
    expect(screen.getByText("13 tasks").className).not.toBe(screen.getByText("P0").className);
  });
});
