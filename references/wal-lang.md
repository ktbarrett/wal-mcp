# WAL Programmer Manual

Version 0.8.2

## 1. Core Language

This section documents the core functionality of WAL including arithmetic, control flow, and data structures.

### Arithmetic

```
(+ expr*) -> (int?)
(- expr*) -> (int?)
(* expr*) -> (int?)
     expr : (int?)

(/ a b) -> (int?)

(** base exponent) -> (int?)
     base : (int?)
 exponent : (int?)
```

Examples:

```
>-> (+ 1 2 3 4)
10
>-> (/ 10 3)
3.3333333333333335
```

### Logic and Comparisons

```
(! expr) -> (int?)
(&& expr*) -> (int?)
(|| expr*) -> (int?)
     expr : (int?), (list?), (array?)
(= expr*) -> (int?)
(!= expr*) -> (int?)

(> a b) -> (int?)
(< a b) -> (int?)
(>= a b) -> (int?)
(<= a b) -> (int?)
        a : (int?)
        b : (int?)
```

Many logical functions such as the logical and `&&` support more than two inputs. In the case of `&&` all arguments must be positive. `1` and `0` are equivalent to the boolean literals `#t` and `#f`.

Examples:

```
>-> (! #f)
#t
>-> (&& #t #t)
#t
>-> (&& #t #t #f)
#f
>-> (&& #t #t #0)
#f
>-> (= 5 5)
#t
>-> (= '(1 2) '(1 2))
#t
```

### Program State

#### let

```
(let ((id expr)+) body)
       id : (symbol?)
     expr : WAL expression
     body : WAL expression
```

The `let` function locally binds the results of the expressions `expr` to the symbols `id` during the evaluation of `body`. The result of the function is the result of the evaluation of the last expression of `body`. Expressions are evaluated in the order they are passed to the function and later bindings can use earlier bindings.

Examples:

```
>-> (let ([x 10])
        x)
10
>-> (let ([x 10]
          [y 12])
         (+ x y))
22
>-> (let ([x 10]
          [y x])
         (+ x y))
20
```

#### define

```
(define id expr)
       id : (symbol?)
     expr : WAL expression
```

Evaluates `expr` and binds the result to `id` and returns the result.

Examples:

```
>-> (define x 10)
10
>-> x
10
>-> (define y (+ x x))
20
```

#### set!

```
(set! id expr)
       id : (symbol?)
     expr : WAL expression
```

Updates the existing binding `id` to the result of evaluating `expr` and returns the result.

Examples:

```
>-> (define x 10)
10
>-> x
10
>-> (set! x (+ x x))
20
>-> x
20
```

### Functions

#### defun

```
(defun name (args+) body+)
     name : (symbol?)
     args : (symbol?) or ((symbol?)+)
     body : WAL expressions
```

New functions can be defined using the `defun` function. The first argument to `defun` is the name to which the new function definition is bound. Following the name, the functions' parameters can be specified. The parameters can either be a list of symbols, or a single symbol. If it is a list of symbols, the function expects one argument for each entry. If a function is called, the arguments to the function are evaluated and bound to the symbols in the argument list `args`. Then, the `body` is evaluated.

Formatting Style: *Typically, the argument list is enclosed in [] braces for better readability.*

Example:

```
>-> (defun times-two [n] (* n 2))
Function: times-two
Args: (n)
(do times-two (* n 2))
>-> (times-two 5)
10
```

If it is a single symbol, all arguments to the function are passed to the function as a list which is bound to the symbol. In this case, the function can accept a variable number of arguments. All following arguments define the expressions of the function body.

Example:

```
>-> (defun times-two-list xs (for/list [x xs] (* x 2)))
Function: times-two-list
Args: xs
(do "times-two-list" (map (lambda (x) (* x 2)) xs))
>-> (times-two-list 1 2 3)
(2 4 6)
```

#### fn

```
(fn (args+) body+)
     args : (symbol?) or ((symbol?)+)
     body : WAL expressions
```

Anonymous functions can be created using the `fn` function.

Example:

```
>-> ((fn [a b] (+ a b)) 1 2)
3
```

WAL has closures, thus functions can capture variables.

```
(defun make-counter [name]
  (define cnt 0)
  (fn [] (set! cnt (+ cnt 1))
         (print name ": " cnt)))

(define cnt1 (make-counter "Cnt1"))
(define cnt2 (make-counter "Cnt2"))
(cnt1)
(cnt1)
(cnt2)
(cnt1)
```

Running this program produces following output.

```
Cnt1: 1
Cnt1: 2
Cnt2: 1
Cnt1: 3
```

### Control Flow

#### do

```
(do body+)
     body : WAL expression
```

Evaluates the expressions in body in order and returns the result of the last element in `body`. Useful to evaluate multiple expressions in places where only one expression is allowed (e.g., in `if` expressions).

#### when

```
(when cond body+)
     cond : WAL expression
     body : WAL expression
```

Evaluates the expressions in body in order and returns the result of the last element in `body` if `cond` evaluates to a truthy result (i.e., int > 0, #t, or a non empty list). Otherwise returns None.

#### unless

```
(unless cond body+)
     cond : WAL expression
     body : WAL expression
```

Evaluates the expressions in body in order and returns the result of the last element in `body` if `cond` evaluates to a falsy result (i.e., 0, #f, or the empty list). Otherwise returns None.

#### if

```
(if cond then else)
     cond : WAL expression
     then : WAL expression
     else : WAL expression
```

Evaluates `then` and returns the result if `cond` evaluates to a positive result (e.g. int > 0, #t, or a non empty list) otherwise evaluates `else` and returns the result. Both `then` and `else` can only be single expressions. However, if multiple expressions are required they can be wrapped in `do` blocks like shown in the following example.

Example:

```
(if a[2]
  (do (print "Option a")
      (set! a (list))
  (do (print "Option b")
      (set! a (list))))
```

#### cond

```
(cond (guard expr+)+)
    guard : WAL expression
     expr : WAL expression
```

The `cond` function implements a condition with multiple cases. It is a more elegant and flexible way than multiple nested if's. It goes through all clauses and evaluates the `exprs` for the first clause for which `guard` evaluates to a positive result. Returns the evaluated result of the last expression of the chosen clause.

Example:

The example below showcases using `cond` in a recursive function implementing the Fibonacci sequence. If the argument `n` is either 1 or 2 the result of the function is 1 otherwise the last default case (clauses with #t always match) is evaluated which recursively calls `fib`.

```
(defun fib [n]
  (cond [(= n 1) 1]
        [(= n 2) 1]
        [#t (+ (fib (- n 1))
               (fib (- n 2)))]))
```

#### case

```
(case key (value expr+)+)
      key : WAL expression
    value : WAL expression
     expr : WAL expression
```

The `case` function implements a condition with multiple cases. It goes through all clauses, checks if `value` is equal to the evaluated `key`, and, if this is the case, evaluates the corresponding expressions returning the last result. A default value that is returned if no other clause matches can be specified by using `default` as the value.

Example:

```
(case (+ a b)
      [1 "one"]
      [2 "two"]
      [3 "three"]
      [default "> three"])
```

### Printing

#### print

```
(print args*)
      args : WAL expression
```

Evaluates `args` in the order they are passed, prints them to the standard output, and appends a newline.

#### printf

```
(printf format args*)
    format : (string?)
      args : WAL expression
```

C-style printf function. Evaluates `args` in the order they are passed and prints them to the standard output in a format specified by `format`. The formatting string follows the Python printf-style formatting rules.

### Utility

#### eval-file

```
(eval-file file)
     module : (symbol?)
```

With `eval-file`, WAL code in other files can be made available in the executed file. Evaluates the WAL code in `module + .wal` and combines the resulting program state with the current program state of the running program. This means, that definitions inside `file` can overwrite definitions made in the running program.

#### exit

```
(exit code)
      code : (int?)
```

Exits with `code` as the return value.

## 2. Waveform Handling

This section describes functions for loading and handling waveforms.

### load

```
(load file id?) -> ()
   file : string?
     id : symbol?
```

Loads waveform from `file` and registers it in the WAL kernel with `id`. The `id` argument is optional. If no `id` is given, WAL automatically selects ids using the scheme `t0`, `t1`, ...

### unload

```
(unload id) -> ()
  id : symbol?
```

Removes the waveform specified by id from the WAL kernel.

### step

```
(step id amount) -> (boolean?)
      id : symbol?
  amount : int?
```

Step trace id by amount. Both arguments are optional. If no id is provided all traces will be stepped by amount. Returns #f if the end of any loaded trace is reached.

### alias

```
(alias name signal) -> ()
    name : symbol?
  signal : symbol?
```

Introduces an alias for `signal` such that it can be also referenced using `name`. Aliases are compatible with groups and scopes. This means, that if an alias is resolved the current group or scope is appended to its name.

### unalias

```
(unalias name) -> ()
    name : symbol?
```

Removes the alias `name`.

### whenever

```
(whenever cond body+)
    cond : WAL expression
    body : WAL expression
```

Evaluates the `body` expressions on each waveform index at which `cond` evaluates to true. Returns the value of the last body expression evaluated at the last index at which `cond` evaluates to true.

### find

```
(find cond) -> (list?)
    cond : WAL expression
```

Returns a list containing all indices at which `cond` evaluates to true.

### count

```
(count cond) -> (list?)
    cond : WAL expression
```

Returns the number of indices at which `cond` evaluates to true.

### timeframe

```
(timeframe body+)
    body: WAL expression
```

Stores the current `INDEX` of every loaded trace before the evaluation of `body` and restores those indices after `body` is evaluated. Returns the result of the last expression in `body`. This allows performing local time operations (e.g., stepping) without losing the location inside the trace. One example for this are overlapping transactions. E.g., when a transaction starts, step to the end of transaction and afterwards resume from the start of transaction.

Example:

```
(print INDEX)
(timeframe
  (while (! ready) (step))
    (print INDEX))
(print INDEX)
```

## 3. Accessing Signals

The core idea behind WAL is that signals from a loaded waveform can be read by just using their name. This means, that waveform signals behave similarly to variables, except that their value depends on the current INDEX, which is the pointer into the currently loaded waveform.

Examples:

```
>-> (load "trace.vcd")
t0(0) >-> SIGNALS
("tb.a", "tb.b")
t0(0) >-> INDEX
0
t0(0) >-> tb.a
5
t0(0) >-> tb.a@1
6
t0(0) >-> INDEX
0
t0(0) >-> INDEX@1
0
```

### get

```
(get signal) -> (int?)
  name : string?
```

Returns the signal value of the signal specified by argument name.

### slice

```
(slice signal upper lower) -> (int?)
  signal : symbol?
   upper : int?
   lower : int?
```

Evaluates expr and returns the bits or list elements from upper to lower. List slicing follows Python's list slicing semantics.

### reval

```
(reval expr offset) -> (int?)
     expr : WAL expression
   offset : int?
```

First evaluates offset to `evaluated-offset` and then evaluates expression at current index + `evaluated-offset`.

### @ (reval shorthand)

```
expr@off -> (reval expr offset)
     expr : WAL expression
   offset : int?
```

The `@` macro is transformed into a call to `reval`.

Examples:

```
>-> INDEX
5
>-> (reval INDEX -1)
4
>-> INDEX@-1
4
>-> INDEX@(+ 2 2)
9
```

## 4. Groups and Scopes

This section describes functions for analyzing waveforms based on the design hierarchy and related signals. Hardware designs often contain a lot of structural redundancy. This can be exploited since it enables us to write expressions in a generic way. For example, many modules have handshaking interfaces, thus if we write a generic handshaking program that can be applied to all handshaking interfaces in a design we can reduce replicated code.

WAL supports two ways of writing generic code, groups and scopes.

### groups

```
(groups posts*) -> (list?)
  posts : symbol?, string?
```

Returns all partial signal names `pre` for which `pre` + `post` for every `post` in `posts` is a valid signal name.

For example, `(groups '("valid" "ready"))` evaluated on a waveform with signals `top.in_valid`, `top.in_ready`, `top.out_valid`, `top.out_ready` would return the two groups `'("top.in_" "top.out_")`.

### in-groups

```
(in-groups groups expr) -> (list?)
groups : list?
  expr : WAL expression
```

Evaluates `expr` in every group in `groups`. When an expression is evaluated in a group, the group is prepended to every signal name that starts with `#`. For example, `#_ready` would be expanded to `top.in_ready` if evaluated in group `top.in` from the waveform shown before.

Example:

The following example shows how the `in-groups` function can be used to find all transactions on all handshaking interfaces in the waveform. The variable `CG` is a special variable that returns the current group.

```
(in-groups '("top.in_" "top.out_")
  (print CG ":")
  (whenever (&& top.clk (! top.reset) #ready #valid)
    (print INDEX)))
```

### resolve-group

```
(resolve-group name) -> (int?)
  name : (symbol?)
```

Evaluates the signal `name` appended by `CG` and returns the signal value at the current `INDEX`. For example, `(resolve-group #valid)` evaluated in group `top.in_` would evaluate signal `top.in_valid`.

### # (resolve-group shorthand)

```
#name -> (resolve-group name)
  name : (symbol?)
```

A shorthand for the `resolve-group` function.

## 5. Lists

This section describes list functions.

### list

```
(list expr*) -> (list?)
    expr : WAL expression
```

Returns a list whose elements are the evaluated expressions in the order they were passed to the function.

### first / second / last

```
(first xs)
(second xs)
(last xs)
      xs : (list?)
```

Returns the first, second, or last element of list `xs`.

### rest

```
(rest xs)
      xs : (list?)
```

Returns a list containing all but the first element of `xs`.

### in

```
(in x xs)
        x : WAL Expression
       xs : (list?)
```

Returns true if `x` is an element in `xs`.

### min / max

```
(min xs)
(max xs)
       xs : (list?)
```

Returns the smallest or largest element in `xs`.

### sum

```
(sum xs)
       xs : (list?)
```

Returns the sum of all elements in `xs`.

### average

```
(average xs)
       xs : (list?)
```

Returns the average of all elements in `xs`.

### length

```
(length xs)
       xs : (list?)
```

Returns the number of elements in `xs`.

### map

```
(map f xs)
        f : Function (fn [x] ...)
       xs : (list?)
```

Returns a list containing `(f x)` for each `x` in `xs` in the order they appear in `xs`.

## 6. Arrays

This section describes array functions. In WAL, arrays are a hashmap data structure.

### array

```
(array (id expr)*) -> (array?)
  id : WAL value
  expr : WAL expression
```

Constructs an array initialized with the data passed as tuples to this function. Keys are always stored as strings. When printed, arrays are shown in curly braces {} and the entries are shown in parentheses ().

Examples:

```
>-> (array)
{}
>-> (array ['x 10] ['y 20])
{("x" 10) ("y" 20)}
>-> (array [5 5])
{("5" 5)}
```

### seta

```
(seta array key value) -> WAL value
  array : (array?)
  key : WAL value
  value: WAL expression
```

Evaluates `key`, converts the result to string and inserts/updates `value` in `array`.

Examples:

```
>-> (seta (array) 'x 10)
{("x" 10)}
>-> (seta (array ['x 10]) 'y 20)
{("x" 10) ("y" 20)}
>-> (define some-array (array))
{}
>-> (define data '("test" "data"))
("test")
>-> (seta some-array 0 data)
{("0" ("test" "data"))}
```

### geta

```
(geta array key) -> WAL value
  array : (array?)
  key : WAL value
```

Evaluates `key`, converts the result to string and returns the value at `key` from `array`.

Examples:

```
>-> (geta (array ['x 10]) 'x)
10
>-> (define i 5)
5
>-> (geta (array ['i 0] [5 "test"]) i)
"test"
```

### geta/default

```
(geta/default array default key) -> WAL value
  array : (array?)
  default : WAL expression
  key : WAL value
```

Evaluates `key`, converts the result to string and returns the value at `key` from `array` if `key` is in `array` else evaluates and returns `default`.

Examples:

```
>-> (geta/default (array ['x 10]) 5 'x)
10
>-> (geta/default (array ['x 10]) 5 'y)
5
```

### dela

```
(dela array key) -> WAL value
  array : (array?)
  key : WAL value
```

Evaluates `key`, converts the result to string and removes the value at `key` from `array`.

Examples:

```
>-> (dela (array ['x 10] ['y 20]) 'x)
{["y" 20]}
```

### mapa

```
(mapa f array) -> (list?)
  f : (fn?) (fn [key value] ...)
  array : (array?)
```

Applies function `f` to every (key value) pair in `array`. `f` must take exactly two parameters with the first being the key and the second being the value. Returns a list.

Examples:

```
>-> (mapa (fn [k v] (list k v)) (array ['x 10] ['y 20]) 'x)
{["y" 20]}
```

## 7. Types and Conversions

This section describes functions for type conversions.

### atom?

```
(atom? x) -> (boolean?)
     x : WAL expression
```

Returns true if the argument `x` is either a symbol, integer, boolean, symbol, or string. Otherwise returns false.

### Type Predicates

```
(symbol? x) -> (boolean?)
(string? x) -> (boolean?)
   (int? x) -> (boolean?)
  (list? x) -> (boolean?)
       x : WAL expression
```

Predicate functions that return true if the argument `x` is of the checked type. Otherwise returns false.

### convert/bin

```
(convert/bin x width) -> (boolean?)
       x : (int?)
   width : (int?)
```

Converts an integer `x` to a binary string representation with a size of `width` bits.
