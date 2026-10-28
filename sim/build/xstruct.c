/**
 * @file
 *
 * @date Nov 25, 2020
 * @author Attila Kovacs
 *
 * \brief
 *      A collection of commonly used functions for generic structured data exchange.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <search.h>

#define __XCHANGE_INTERNAL_API__      ///< Use internal definitions
#include "xchange.h"


/**
 * Creates a new empty XStructure.
 *
 * \sa smaxDestroyStruct()
 *
 */
XStructure *xCreateStruct() {
  XStructure *s = (XStructure *) calloc(1, sizeof(XStructure));
  x_check_alloc(s);
  return s;
}

/**
 * Creates a field containing an array of heterogeneous fields. Each element of the
 * array may have a different type and/or size.
 *
 * @param name    The name of the array field
 * @param ndim    The dimensionality of the heterogeneous components
 * @param sizes   The individual sizes along each dimension
 * @param array   The XField array of elements containing varying types and dimensions within them.
 * @return        A field containing a heterogeneous array of entries, or NULL if there
 *                was an error. The entries are initially empty, except for their names
 *                bearing '.' followed by the 1-based array index, e.g. '.1', '.2'...
 *
 * @sa xCreateMixed1DField()
 */
XField *xCreateMixedArrayField(const char *name, int ndim, const int *sizes, XField *array) {
  int count = xGetElementCount(ndim, sizes);
  XField *f;

  f = xCreateField(name, X_FIELD, ndim, sizes, array);
  if(f == NULL) return x_trace_null("xCreateMixedArrayField", NULL);

  while(--count >= 0) {
    char idx[20];
    sprintf(idx, ".%d", (count+1));
    array[count].name = xStringCopyOf(idx);
  }

  return f;
}

/**
 * Creates a field containing a 1D array of heterogeneous fields. Each element of the
 * array may have a different type and/or size.
 *
 * @param name    The name of the array field
 * @param size    The number of heterogeneous fields in the array.
 * @param array   The XField array of rows containing varying types and dimensions within them.
 * @return        A field containing a heterogeneous array of entries, or NULL if there
 *                was an error. The entries are initially empty, except for their names
 *                bearing '.' followed by the 1-based array index, e.g. '.1', '.2'...
 *
 * @sa xCreateMixedArrayField()
 */
XField *xCreateMixed1DField(const char *name, int size, XField *array) {
  const int sizes[X_MAX_DIMS] = { size };
  return xCreateMixedArrayField(name, 1, sizes, array);
}

/**
 * Returns a deep copy of the supplied structure. Note that this only works with vanilla xchange structures
 * with native storage fields. For example, SMA-X structures store data in serialized forms, and therefore it
 * needs its own implementation for making deep copies of structs!
 *
 * @param s     Pointer to the original structure or NULL.
 * @return      A fully independent (deep) copy of the argument or NULL if the input structure is NULL.
 *
 * @sa xCopyOfField()
 */
XStructure *xCopyOfStruct(const XStructure *s) {
  static const char *fn = "xCopyOfStruct";

  XStructure *copy;
  XField *f, *last = NULL;

  if(!s) {
    x_error(0, EINVAL, fn, "input structure is NULL");
    return NULL;
  }

  copy = xCreateStruct();

  for(f = s->firstField; f != NULL; f = f->next) {
    XField *cf = xCopyOfField(f);
    if(!cf) {
      xDestroyStruct(copy);
      return x_trace_null(fn, NULL);
    }

    if(f->type == X_STRUCT) if(f->value) {
      // Set the copy as the parent structure for any copied substructures.
      XStructure *sub = (XStructure *) f->value;
      int k;
      for(k = xGetFieldCount(f); --k >= 0; ) sub[k].parent = copy;
    }

    if(last) last->next = cf;
    else copy->firstField = cf;

    last = cf;
  }

  return copy;
}

/**
 * Returns a deep copy of the supplied field. The returned copy is a standalone field, unlinked
 * to another to avoid corrupting any structure in which the original field may reside in.
 * Note, that this only works with vanilla xchange structures with native storage fields. For example,
 * SMA-X structures store data in serialized forms, and therefore it needs its own implementation for
 * making deep copies of fields!
 *
 * @param f     Pointer to the original field or NULL.
 * @return      A fully independent (deep) copy of the argument or NULL if the input field is NULL.
 *
 * @sa xCopyOfStruct()
 */
XField *xCopyOfField(const XField *f) {
  static const char *fn = "xCopyOfField";

  XField *copy;
  int k, n, eCount;

  if(!f) {
    x_error(0, EINVAL, fn, "input field is NULL");
    return NULL;
  }

  copy = (XField *) calloc(1, sizeof(XField));
  x_check_alloc(copy);

  // Start with a clone...
  *copy = *f;

  copy->name = NULL;        // To be assigned below...
  copy->subtype = NULL;     // To be assigned below...
  copy->value = NULL;       // To be assigned below...
  copy->next = NULL;        // Clear the link of the copy to avoid corrupted structures.

  if(f->name) {
    copy->name = xStringCopyOf(f->name);
    if(!copy->name) {
      xDestroyField(copy);
      return x_trace_null(fn, f->name);
    }
  }

  if(f->subtype) {
    copy->subtype = xStringCopyOf(f->subtype);
    if(!copy->subtype) {
      xDestroyField(copy);
      return x_trace_null(fn, f->name);
    }
  }

  if(!f->value) return copy;

  // Copy data
  // -----------------------------------------------------------------------------------

  if(f->type == X_STRUCT) {
    XStructure *s = (XStructure *) f->value, *c;
    eCount = xGetFieldCount(f);

    if(eCount <= 0) return copy;

    c = (XStructure *) calloc(eCount, sizeof(XStructure));
    if(!c) {
      x_error(0, errno, fn, "alloc error (%d XStructure)", eCount);
      xDestroyField(copy);
      return NULL;
    }
    copy->value = (char *) c;

    for(k = 0; k < eCount; k++) {
      XStructure *e = xCopyOfStruct(&s[k]);
      if(!e) {
        xDestroyField(copy);
        return x_trace_null(fn, f->name);
      }
      c[k] = *e;
      free(e);
    }

    return copy;
  }

  // -----------------------------------------------------------------------------------

  if(f->isSerialized) {
    copy->value = xStringCopyOf(f->value);
    if(!copy->value) {
      x_trace_null(fn, "serialized value");
      xDestroyField(copy);
      return NULL;
    }
    return copy;
  }

  // -----------------------------------------------------------------------------------

  eCount = xGetFieldCount(f);
  if(eCount <= 0) return copy;

  n = eCount * xElementSizeOf(f->type);
  if(n <= 0) return copy;

  // Allocate the copy value storage.
  copy->value = (char *) malloc(n);
  if(!copy->value) {
    x_error(0, errno, fn, "field %s alloc error (%d bytes)", f->name, n);
    xDestroyField(copy);
    return NULL;
  }

  if(f->type == X_FIELD) {
    XField *src = (XField *) f->value;
    XField *dst = (XField *) copy->value;
    for(k = 0; k < eCount; k++) {
      XField *tmp = xCopyOfField(&src[k]);
      dst[k] = *tmp;  // Copy to destination with references.
      free(tmp);      // Empty the temporary container.
    }
  }

  else if(f->type == X_RAW) {
    // raw value is single string pointer
    char **src = (char **) f->value;
    if(*src) {
      char *str = xStringCopyOf(*src);
      if(*src) copy->value =  &str;
    }
  }

  else if(f->type == X_STRING) {
    char **src = (char **) f->value;
    char **dst = (char **) copy->value;
    for(k = 0; k < eCount; k++) dst[k] = xStringCopyOf(src[k]);
  }
  else memcpy(copy->value, f->value, n);

  return copy;
}


/**
 * Return the reference to the field by the specified name, or NULL if no such field exists.
 *
 * \param s     Structure from which to retrieve a given field.
 * \param id    Name or aggregate ID of the field to retrieve
 *
 * \return      Matching field from the structure or NULL if there is no match or one of
 *              the arguments is NULL.
 *
 * \sa xGetAsLong()
 * \sa xGetAsDouble()
 * \sa xLookupField()
 * \sa xSetField()
 * \sa xGetSubstruct()
 */
XField *xGetField(const XStructure *s, const char *id) {
  static const char *fn = "xGetField";

  XField *e;

  if(s == NULL) {
    x_error(0, EINVAL, fn, "input structure is NULL");
    return NULL;
  }
  if(id == NULL) {
    x_error(0, EINVAL, fn, "input id is NULL");
    return NULL;
  }

  for(e = s->firstField; e != NULL; e = e->next) if(e->name) if(xMatchNextID(e->name, id) == X_SUCCESS) {
    const char *next = xNextIDToken(id);
    if(!next) return e;

    if(e->type != X_STRUCT) return NULL;
    return xGetField((XStructure *) e->value, next);
  }

  return NULL;
}

/**
 * Return a signed integer value associated to the field, or else the specified default value if the
 * field cannot be represented as an integer. This call will use both widening and narrowing
 * conversions, and rounding, as necessary to convert between numerical types (e.g. `float` to
 * `long`), while for string values will attempt to parse an integer value.
 *
 * If the field is an array, the first element is converted and returned.
 *
 * @param f                 Pointer to a field.
 * @param defaultValue      The value to return if the structure contains no field with the
 *                          specified ID, or if it cannot be represented as an integer
 *                          though narrowing or widening conversions, rounding, or through
 *                          parsing.
 *
 * @return      The value of the field, represented as an integer, if possible, or else the
 *              specified default value. In case of error `errno` will be set to a non-zero value
 *              indicating the type of error.
 *
 * @sa xGetAsLongAtIndex()
 * @sa xGetAsDouble()
 * @sa xGetStringValue()
 *
 */
long xGetAsLong(const XField *f, long defaultValue) {
  long x;

  errno = 0;
  x = xGetAsLongAtIndex(f, 0, defaultValue);
  if(errno) x_trace("xGetAsLong", NULL, x);

  return x;
}

/**
 * Return a signed integer value associated to the value at the specified array index in the field,
 * or else the specified default value if the element cannot be represented as an integer. This
 * call will use both widening and narrowing conversions, and rounding, as necessary to convert
 * between numerical types (e.g. `float` to `long`), while for string values will attempt to
 * parse an integer value.
 *
 * @param f                 Pointer to a field.
 * @param idx               Array index (zero-based) of the element of interest.
 * @param defaultValue      The value to return if the structure contains no field with the
 *                          specified ID, or if it cannot be represented as an integer
 *                          though narrowing or widening conversions, rounding, or through
 *                          parsing.
 *
 * @return      The value of the field, represented as an integer, if possible, or else the
 *              specified default value. In case of error `errno` will be set to a non-zero value
 *              indicating the type of error.
 *
 * @sa xGetAsLong()
 * @sa xGetAsDoubleAtIndex()
 * @sa xGetStringAtIndex()
 */
long xGetAsLongAtIndex(const XField *f, int idx, long defaultValue) {
  static const char *fn = "xGetAsLongAtIndex";

  const void *ptr;

  if(!f) return x_error(defaultValue, EINVAL, fn, "input field is NULL");
  if(!f->value) return x_error(defaultValue, EFAULT, fn, "field has NULL value");
  if(f->isSerialized) return x_error(defaultValue, ENOSR, fn, "cannot convert serialized field");

  errno = 0;

  ptr = xGetElementAtIndex(f, idx);
  if(!ptr) {
    if(errno) x_trace(fn, NULL, defaultValue);
    return defaultValue;
  }

  if(xIsCharSequence(f->type)) {
    long l = defaultValue;
    char fmt[20];

    sprintf(fmt, "%%%dd", xElementSizeOf(f->type));
    if(sscanf((char *) ptr, fmt, &l) != 1) {
      double d = NAN;
      sprintf(fmt, "%%%dlf", xElementSizeOf(f->type));
      if(sscanf((char *) ptr, fmt, &d) == 1) return (long) floor(d + 0.5);
    }

    return l;
  }

  switch(f->type) {
    case X_BOOLEAN: return *(boolean *) ptr;
    case X_BYTE: return *(int8_t *) ptr;
    case X_INT16: return *(int16_t *) ptr;
    case X_INT32: return *(int32_t *) ptr;
    case X_INT64: return *(int64_t *) ptr;
    case X_FLOAT: {
      const float *x = (float *) ptr;
      return (long) floor(*x + 0.5);
    }
    case X_DOUBLE: {
      const double *x = (double *) ptr;
      return (long) floor(*x + 0.5);
    }
    case X_STRING:
    case X_RAW: {
      double d = 0.0;
      errno = 0;
      d = strtod(ptr, NULL);
      return (errno ? defaultValue : d);
    }
    default:
      return defaultValue;
  }
}

/**
 * Return a double-precision floating point value associated to the field, or else NAN if the field
 * cannot be represented as a decimal value. This call will use widening conversions as necessary to
 * convert between numerical types (e.g. `short` to `double`), while for string values will attempt
 * to parse a decomal value.
 *
 * If the field is an array, the first element is converted and returned.
 *
 * @param f                 Pointer to field
 *
 * @return      The value of the field, represented as a double-precision floating point value, if
 *              possible, or else NAN. In case of error `errno` will be set to a non-zero value
 *              indicating the type of error.
 *
 * @sa xGetAsDoubleAtIndex()
 * @sa xGetAsLong()
 * @sa xGetStringValue()
 */
double xGetAsDouble(const XField *f) {
  double x;

  errno = 0;
  x = xGetAsDoubleAtIndex(f, 0);
  if(errno) x_trace_null("xGetAsDouble", NULL);
  return x;
}

/**
 * Return a double-precision floating point value associated to the field, or else NAN if the element
 * cannot be represented as a decimal value. This call will use widening conversions as necessary to
 * convert between numerical types (e.g. `short` to `double`), while for string values will attempt
 * to parse a decomal value.
 *
 * @param f     Pointer to field
 * @param idx   Array index (zero-based) of the element of interest.
 *
 * @return      The value of the field, represented as a double-precision floating point value, if
 *              possible, or else NAN. In case of error `errno` will be set to a non-zero value
 *              indicating the type of error.
 *
 * @sa xGetAsDouble()
 * @sa xGetAsLongAtIndex()
 * @sa xGetStringAtIndex()
 */
double xGetAsDoubleAtIndex(const XField *f, int idx) {
  static const char *fn = "xGetAsDoubleAtIndex";

  const void *ptr;

  if(!f) {
    x_error(0, EINVAL, fn, "input field is NULL");
    return NAN;
  }

  if(!f->value) {
    x_error(0, EFAULT, fn, "field has NULL value");
    return NAN;
  }

  if(f->isSerialized) {
    x_error(0, ENOSR, fn, "cannot convert serialized field");
    return NAN;
  }

  errno = 0;

  ptr = xGetElementAtIndex(f, idx);
  if(!ptr) {
    if(errno) x_trace_null(fn, NULL);
    return NAN;
  }

  if(xIsCharSequence(f->type)) {
    char fmt[20];
    double d = NAN;
    sprintf(fmt, "%%%dlf", xElementSizeOf(f->type));
    sscanf((char *) ptr, fmt, &d);
    return d;
  }

  if(xIsCharSequence(f->type)) {
    double d = 0.0;
    errno = 0;
    d = strtod(ptr, NULL);
    if(errno) return NAN;
    return d;
  }

  switch(f->type) {
    case X_BOOLEAN: return *(boolean *) ptr;
    case X_BYTE: return *(int8_t *) ptr;
    case X_INT16: return *(int16_t *) ptr;
    case X_INT32: return *(int32_t *) ptr;
    case X_INT64: return *(int64_t *) ptr;
    case X_FLOAT: {
      const float *x = (float *) ptr;
      return (long) floor(*x + 0.5);
    }
    case X_DOUBLE: {
      const double *x = (double *) ptr;
      return (long) floor(*x + 0.5);
    }
    case X_STRING:
    case X_RAW: {
      double d = 0.0;
      errno = 0;
      d = strtod(ptr, NULL);
      return (errno ? NAN : d);
    }
    default: return NAN;
  }
}

/**
 * Returns a reference to the string value stored in the field, or else NULL if the element is not string
 * typed. Only fields containing X_STRING or X_RAW type values, or fixed-sized character sequences
 * (XCHARS(n) type), can will return a pointer reference to the value. Or, if the field is in serialized form,
 * then the pointer to the serialized value is returned.For fixed-length character sequences the string
 * pointed at may not be null-terminated.
 *
 * If the field is an array, the first element is returned.
 *
 * @param f                 Pointer to field
 *
 * @return      Pointer to the string value of the field or NULL. In case of error `errno` will be set to
 *              a non-zero value indicating the type of error.
 *
 * @sa xGetStringAtIndex()
 * @sa xGetAsLong()
 * @sa xGetAsDouble()
 */
char *xGetStringValue(const XField *f) {
  char *str;

  errno = 0;
  str = xGetStringAtIndex(f, 0);
  if(errno) x_trace_null("xGetStringValue", NULL);
  return str;
}

/**
 * Returns a reference to the string value at the specified array index in the field, or else NULL if
 * the element is not string typed, or if the index is out of bounds. Only fields containing X_STRING
 * or X_RAW type values, or fixed-sized character sequences (XCHARS(n) type), can will return a pointer
 * reference to the value. Or, if the field is in serialized form, then the pointer to the serialized
 * value is returned. For fixed-length character sequences the string pointed at may not be
 * null-terminated.
 *
 * @param f     Pointer to field
 * @param idx   Array index (zero-based) of the element of interest.
 *
 * @return      Pointer to the string value of the field or NULL. In case of error `errno` will be set to
 *              a non-zero value indicating the type of error.
 *
 * @sa xGetStringValue()
 * @sa xGetAsLongAtIndex()
 * @sa xGetDoubleAtIndex()
 */
char *xGetStringAtIndex(const XField *f, int idx) {
  static const char *fn = "xGetStringAtIndex";

  const void *ptr;

  if(!f) {
    x_error(0, EINVAL, fn, "input field is NULL");
    return NULL;
  }

  if(!f->value) {
    x_error(0, EFAULT, fn, "field has NULL value");
    return NULL;
  }

  if(f->isSerialized) return (char *) f->value;

  if(f->type != X_STRING && f->type != X_RAW && !xIsCharSequence(f->type)) {
    x_error(0, EINVAL, fn, "field is not string: type %d\n", f->type);
    return NULL;
  }

  errno = 0;

  ptr = xGetElementAtIndex(f, idx);
  if(!ptr) {
    if(errno) x_trace_null(fn, NULL);
    return NULL;
  }

  if(xIsCharSequence(f->type)) return (char *) ptr;

  return *(char **) ptr;
}

/**
 * Returns a substructure by the specified name, or NULL if no such sub-structure exists.
 *
 * \param s   Structure from which to retrieve a given sub-structure.
 * \param id  Name or aggregate ID of the substructure to retrieve
 * \return    Matching sub-structure from the structure or NULL if there is no match or one of
 *            the arguments is NULL.
 *
 * \sa xSetSubstruct()
 * \sa xGetField()
 */
XStructure *xGetSubstruct(const XStructure *s, const char *id) {
  static const char *fn = "xGetSubstruct";

  const XField *f;

  if(!s) {
    x_error(0, EINVAL, fn, "input structure is NULL");
    return NULL;
  }
  if(!id) {
    x_error(0, EINVAL, fn, "input field name is NULL");
    return NULL;
  }
  if(!id[0]) {
    x_error(0, EINVAL, fn, "input field name is empty");
    return NULL;
  }

  f = xGetField(s, id);

  if(f && f->type == X_STRUCT)
    return (XStructure *) f->value;

  return NULL;
}

/**
 * Creates a generic field of a given name and type and dimensions using a copy of the specified native data,
 * unless type is X_STRUCT in which case the value is referenced directly inside the field.
 *
 * \param name      Field name (it may not contain a separator X_SEP)
 * \param type      Storage type, e.g. X_INT.
 * \param ndim      Number of dimensionas (1:20). If ndim < 1, it will be reinterpreted as ndim=1, size[0]=1;
 * \param sizes     Array of sizes along each dimensions, with at least ndim elements, or NULL with ndim<1.
 * \param value     Pointer to the native data location in memory, or NULL to leave unassigned for now.
 *
 * \return          A newly created field with the copy of the supplied data, or NULL if there was an error.
 */
XField *xCreateField(const char *name, XType type, int ndim, const int *sizes, const void *value) {
  static const char *fn = "xCreateField";
  XField *f;
  int count, n;

  if(!name) {
    x_error(0, EINVAL, fn, "name is NULL");
    return NULL;
  }
  if(!name[0]) {
    x_error(0, EINVAL, fn, "name is empty");
    return NULL;
  }

  if(xLastSeparator(name)) {
    x_error(0, EINVAL, fn, "name contains separator: %s", name);
    return NULL;
  }

  if(ndim > X_MAX_DIMS) {
    x_error(0, EINVAL, fn, "too many dimensions: %d", ndim);
    return NULL;
  }

  if(type == X_RAW) ndim = 0;

  count = xGetElementCount(ndim, sizes);
  n = count * xElementSizeOf(type);

  if(n < 0) {
    x_error(0, ERANGE, fn, "invalid size: count=%ld, eSize=%d", xGetElementCount(ndim, sizes), xElementSizeOf(type));
    return NULL;
  }

  f = (XField *) calloc(1, sizeof(XField));
  x_check_alloc(f);

  f->name = xStringCopyOf(name);
  if(!f->name) {
    free(f);
    return x_trace_null(fn, "copy of name");
  }

  f->type = type;

  if(ndim < 1) {
    f->ndim = 0;
    f->sizes[0] = 1;
  }
  else {
    f->ndim = ndim;
    memcpy(f->sizes, sizes, sizeof(f->sizes));
  }

  if(!value) {
    f->value = NULL;
    return f;
  }

  if(type == X_STRUCT) {
    f->value = (char *) value;
    return f;
  }

  f->value = (char *) malloc(n);

  if(!f->value) {
    x_error(0, errno, fn, "alloc error (%d bytes)", n);
    xDestroyField(f);
    return NULL;
  }

  if(f->type == X_STRING || f->type == X_RAW) {
    const char **src = (const char **) value;
    char **dst = (char **) f->value;
    int i;
    for(i = 0; i < count; i++) dst[i] = xStringCopyOf(src[i]);
  }
  else memcpy(f->value, value, n);

  return f;
}


/**
 * Creates a generic scalar field of a given name and native value. The structure will hold a copy
 * of the value that is pointed at.
 *
 * \param name      Field name (it may not contain a separator X_SEP)
 * \param type      Storage type, e.g. X_INT.
 * \param value     Pointer to the native data location in memory.
 *
 * \return          A newly created field with the supplied data, or NULL if there was an error.
 */
XField *xCreateScalarField(const char *name, XType type, const void *value) {
  XField *f = xCreateField(name, type, 0, NULL, value);
  if(!f) return x_trace_null("xCreateScalarField", NULL);
  return f;
}

/**
 * Creates a generic field for a 1D array of a given name and native data. The structure will hold a
 * copy of the value that is pointed at.
 *
 * \param name      Field name (it may not contain a separator X_SEP)
 * \param type      Storage type, e.g. X_INT.
 * \param count     Number of elements in array
 * \param values    Pointer to an array of native values.
 *
 * \return          A newly created field with the supplied data, or NULL if there was an error.
 */
XField *xCreate1DField(const char *name, XType type, int count, const void *values) {
  const int sizes[] = { count };
  XField *f = xCreateField(name, type, 1, sizes, values);
  if(!f) return x_trace_null("xCreate1DField", NULL);
  return f;
}

/**
 * Creates a field holding a single double-precision value value.
 *
 * \param name      Field name (it may not contain a separator X_SEP)
 * \param value     Associated value
 *
 * \return          A newly created field with the supplied data, or NULL if there was an error.
 *
 */
XField *xCreateDoubleField(const char *name, double value) {
  XField *f = xCreateScalarField(name, X_DOUBLE, &value);
  if(!f) return x_trace_null("xCreateDoubleField", NULL);
  return f;
}

/**
 * Creates a field holding a single ineger value value.
 *
 * \param name      Field name (it may not contain a separator X_SEP)
 * \param value     Associated value
 *
 * \return          A newly created field with the supplied data, or NULL if there was an error.
 *
 * @sa xCreateLongField()
 */
XField *xCreateIntField(const char *name, int value) {
  XField *f = xCreateScalarField(name, X_INT, &value);
  if(!f) return x_trace_null("xCreateIntField", NULL);
  return f;
}

/**
 * Creates a field holding a single ineger value value.
 *
 * \param name      Field name (it may not contain a separator X_SEP)
 * \param value     Associated value
 *
 * \return          A newly created field with the supplied data, or NULL if there was an error.
 *
 * @sa xCreateIntField()
 */
XField *xCreateLongField(const char *name, long long value) {
  XField *f = xCreateScalarField(name, X_LLONG, &value);
  if(!f) return x_trace_null("xCreateLongField", NULL);
  return f;
}


/**
 * Creates a field holding a single boolean value value.
 *
 * \param name      Field name (it may not contain a separator X_SEP)
 * \param value     Associated value
 *
 * \return          A newly created field with the supplied data, or NULL if there was an error.
 */
XField *xCreateBooleanField(const char *name, boolean value) {
  XField *f = xCreateScalarField(name, X_BOOLEAN, &value);
  if(!f) return x_trace_null("xCreateBooleanField", NULL);
  return f;
}


/**
 * Creates a field holding a single string value. The field will hold a copy of the supplied
 * value, so the caller may destroy the string safely after the call.
 *
 * \param name      Field name (it may not contain a separator X_SEP)
 * \param value     Associated value (it may be NULL). The string will be copied, not referenced.
 *
 * \return          A newly created field referencing the supplied string, or NULL if there was an error.
 */
XField *xCreateStringField(const char *name, const char *value) {
  XField *f = xCreateScalarField(name, X_STRING, &value);
  if(!f) return x_trace_null("xCreateStringField", NULL);
  return f;
}

/**
 * Sets the optional subtype for a field's content to a copy of the specified string value. The
 * subtype can be used to add any application specific information on how the specified value
 * should be used. For example it may indicate a mime type or an encoding. It is entirely up to
 * the user as to what meaning the subtype has for their application.
 *
 * @param f       Pointer to a field
 * @param type    The new subtype to be assigned to the field. A copy of the value is used rather
 *                than the reference, so that the string that was supplied can be safely discarded
 *                at any point after the call.
 * @return        X_SUCCESS (0) if successful or else X_NULL if the intput field pointer is NULL.
 */
int xSetSubtype(XField *f, const char *type) {
  if(!f) return x_error(X_NULL, EINVAL, "xSetSubtype", "input field is NULL");
  if(f->subtype) free(f->subtype);
  f->subtype = xStringCopyOf(type);
  return X_SUCCESS;
}

/**
 * Checks if a given field has valid data.
 *
 * \param f         Pointer to the field to check.
 *
 * \return          TRUE is the field seems to contain valid data, otherwise FALSE.
 *
 */
boolean xIsFieldValid(const XField *f) {
  int i;
  if(f->name == NULL) return FALSE;
  if(xLastSeparator(f->name)) return FALSE;
  if(f->value == NULL) return FALSE;
  if(f->type == X_STRUCT) return TRUE;
  if(xElementSizeOf(f->type) <= 0) return FALSE;
  if(f->ndim < 0) return FALSE;
  for(i=0; i <f->ndim; i++) if(f->sizes[0] <= 0) return FALSE;
  return TRUE;
}

/**
 * Returns the total number of primitive elements in a field.
 *
 * @param f     The field
 * @return      The total number of primitive elements contained in the field.
 */
long xGetFieldCount(const XField *f) {
  if(!f) {
    x_error(0, EINVAL, "xGetFieldCount", "input field is NULL");
    return 0;
  }
  return xGetElementCount(f->ndim, f->sizes);
}

/**
 * Returns a pointer to the array element at the specified index.
 *
 * @param f     Pointer to a field
 * @param idx   the array index of the requested element
 *
 * @return      A pointer to the element at the given index, or NULL if there was an error.
 *
 * @sa xGetAsLongAtIndex()
 * @sa xGetAsDoubleAtIndex()
 * @sa xGetStringAtIndex()
 */
void *xGetElementAtIndex(const XField *f, int idx) {
  static const char *fn = "xGetElementAtIndex";

  int n, eSize;

  if(idx < 0) {
    x_error(0, EINVAL, fn, "negative index");
    return NULL;
  }

  n = xGetFieldCount(f);
  if(n < 0) return x_trace_null(fn, NULL);

  if(idx >= n) {
    x_error(0, EINVAL, fn, "index %d is out of bounds for element count %d", idx, n);
    return NULL;
  }

  eSize = xElementSizeOf(f->type);
  if(eSize < 0) return x_trace_null(fn, NULL);

  return (char *) f->value + idx * eSize;
}

/**
 * Inserts a structure within a parent structure, returning the old field that may have existed under
 * the requested name before.
 *
 * The name may not contain a compound ID. To add the structure to embedded sub-structures, you may want to
 * use xGetSubstruct() first to add the new structure directly to the relevant embedded component.
 *
 * \param s         Pointer to the parent structure
 * \param name      Name of the sub-structure
 * \param substruct Pointer to the sub-structure. It is added directly as a reference, without making a copy.
 *
 * return           The prior field stored under the same name or NULL. If there is an error
 *                  then NULL is returned and errno is set to indicate the nature of the issue.
 *                  (a message is also printed to stderr if xDebug is enabled.)
 *
 * \sa xGetSubstruct()
 */
XField *xSetSubstruct(XStructure *s, const char *name, XStructure *substruct) {
  static const char *fn = "xSetSubstruct";
  XField *f;

  if(!s) {
    x_error(0, EINVAL, fn, "input structure is NULL");
    return NULL;
  }

  if(!name) {
    x_error(0, EINVAL, fn, "input name is NULL");
    return NULL;
  }

  if(!name[0]) {
    x_error(0, EINVAL, fn, "input name is empty");
    return NULL;
  }

  if(!substruct) {
    x_error(0, EINVAL, fn, "input sub-structure is NULL");
    return NULL;
  }

  if(substruct->parent) {
    x_error(0, EALREADY, fn, "input substructure is already assigned");
    return NULL;
  }

  f = xCreateScalarField(name, X_STRUCT, substruct);
  if(!f) return x_trace_null(fn, name);

  substruct->parent = s;

  return xSetField(s, f);
}

/**
 * Removes as field from the structure, returning it if found.
 *
 * \param s     Pointer to structure
 * \param name  Name of field to remove
 *
 * \return      Pointer to the removed field or else NULL if the was an error or if no
 *              matching field existed in the structure.
 *
 */
XField *xRemoveField(XStructure *s, const char *name) {
  static const char *fn = "xRemoveField";

  XField *e, *last = NULL;

  if(!s) {
    x_error(0, EINVAL, fn, "input structure is NULL");
    return NULL;
  }

  if(!name) {
    x_error(0, EINVAL, fn, "input name is NULL");
    return NULL;
  }

  if(!name[0]) {
    x_error(0, EINVAL, fn, "input name is empty");
    return NULL;
  }

  for(e = s->firstField; e != NULL; e = e->next) {
    if(!strcmp(name, e->name)) {
      if(last) last->next = e->next;
      else s->firstField = e->next;
      e->next = NULL;
      if(e->type == X_STRUCT) if(e->value) {
        XStructure *sub = (XStructure *) e->value;
        int k = xGetFieldCount(e);
        while(--k >= 0) sub[k].parent = NULL;
      }
      return e;
    }
    last = e;
  }

  return NULL;
}

/**
 * (<i>expert</i>) Inserts a field into the structure at its head position. That is, the specified field will become
 * the first field in the structure. And, unlike xSetField(), this function does not check for (nor remove) previously
 * present fields by the same name. Thus, it is left up to the caller to ensure that there are no duplicate field
 * names added to the structure.
 *
 * A note of caution: There is no safeguard against adding the same field to more than one structure, which will
 * result in a corruption of the affected structures, since both structures would link to the field, but the field
 * links to only one specific successive element. Therefore, the user is responsible to ensure that fields are
 * assigned to structures uniquely, and if necessary remove the field from one structure before assigning it to
 * another.
 *
 * \param s     Structure to which to add the field
 * \param f     Field to be added.
 *
 *
 * \sa xSetField()
 * \sa xReverseFieldOrder()
 */
int xInsertField(XStructure *s, XField *f) {
  static const char *fn = "xInsertField";

  if(!s) return x_error(X_STRUCT_INVALID, EINVAL, fn, "input structure is NULL");
  if(!f) return x_error(X_NULL, EINVAL, fn, "input field is NULL");
  if(!f->name) return x_error(X_NAME_INVALID, EINVAL, fn, "field->name is NULL");
  if(!f->name[0]) return x_error(X_NAME_INVALID, EINVAL, fn, "field->name is empty");

  // The field name contains a separator?
  if(xLastSeparator(f->name)) return x_error(X_NAME_INVALID, EINVAL, fn, "field->name contains separator");

  // Add the new field at the head of the list...
  f->next = s->firstField;
  s->firstField = f;

  return X_SUCCESS;
}

/**
 * Adds or replaces a field in the structure with the specified field value, returning the previous value for the same field.
 * It is up to the caller whether or not the old value should be destoyed or kept. Note though that you should check first to
 * see if the replaced field is the same as the new one before attempting to destroy...
 *
 * The field's name may not contain a compound ID. To add fields to embedded sub-structures, you may want to use
 * xGetSubstruct() first to add the field directly to the relevant embedded component.
 *
 * A note of caution: There is no safeguard against adding the same field to more than one structure, which will result in
 * a corruption of the affected structures, since both structures would link to the field, but the field links to only
 * one specific successive element. Therefore, the user is responsible to ensure that fields are assigned to structures
 * uniquely, and if necessary remove the field from one structure before assigning it to another.
 *
 * \param s     Structure to which to add the field
 * \param f     Field to be added.
 *
 * \return      Previous field by the same name, or NULL if the field is new or if there was an error
 *              (errno will be set to EINVAL)
 *
 * \sa xInsertField()
 * \sa xSetSubstruct()
 * \sa xGetSubstruct()
 */
XField *xSetField(XStructure *s, XField *f) {
  static const char *fn = "xSetField";

  XField *e, *last = NULL;

  if(!s) {
    x_error(0, EINVAL, fn, "input structure is NULL");
    return NULL;
  }

  if(!f) {
    x_error(0, EINVAL, fn, "input field is NULL");
    return NULL;
  }

  if(!f->name) {
    x_error(0, EINVAL, fn, "input field->name is NULL");
    return NULL;
  }

  if(!f->name[0]) {
    x_error(0, EINVAL, fn, "input field->name is empty");
    return NULL;
  }

  f->next = NULL;

  for(e = s->firstField; e != NULL; e = e->next) {
    if(!strcmp(f->name, e->name)) {

      f->next = e->next;                    // Inherit the link to the successive field
      e->next = NULL;                       // Unlink the prior field by the same name.

      if(last == NULL) s->firstField = f;   // If it's right at the top, then replace the top.
      else last->next = f;                  // Otherwise, link to the prior field.

      return e;
    }

    last = e;
  }

  // Add the new field at the end of the list...
  if(last == NULL) s->firstField = f;
  else last->next = f;

  return NULL;
}

/**
 * Returns the number of fields contained inside the structure. It is not recursive.
 *
 * @param s     Pointer to the structure to investigate
 * @return      the number of fields cotnained in the structure (but not counting fields in sub-structures).
 *
 * @sa xDeepCountFields()
 */
int xCountFields(const XStructure *s) {
  const XField *f;
  int n = 0;

  if(!s) return 0;

  for(f = s->firstField; f != NULL; f = f->next) n++;

  return n;
}

/**
 * Destroys an X structure, freeing up resources used by name and value.
 *
 * \param s     Pointer to the structure to be destroyed.
 *
 */
void xDestroyStruct(XStructure *s) {
  if(s == NULL) return;
  xClearStruct(s);
  free(s);
}

/**
 * Clears an X structure field, freeing up all referfenced resources. However, the
 * field itself is kept, but its contents are reset.
 *
 * \param f     Pointer to the field to be cleared.
 *
 * \sa xDestroyField()
 */
void xClearField(XField *f) {
  if(!f) return;

  if(f->value != NULL) {
    switch(f->type) {
      case X_STRUCT: {
        XStructure *sub = (XStructure *) f->value;
        int i = xGetFieldCount(f);
        while(--i >= 0) xClearStruct(&sub[i]);
        break;
      }

      case X_FIELD: {
        XField *array = (XField *) f->value;
        int i;
        for(i = xGetFieldCount(f); --i >=0;) xClearField(&array[i]);
        break;
      }

      case X_RAW: {
        // raw value is single string pointer
        char **str = (char **) f->value;
        if(*str) free(*str);
        break;
      }

      case X_STRING:
        if(!f->isSerialized) {
          // value is an array of string pointers...
          char **str = (char **) f->value;
          int i = xGetFieldCount(f);
          while(--i >= 0) if(str[i]) free(str[i]);
        }
        break;
    }

    free(f->value);
  }

  if(f->name != NULL) free(f->name);
  if(f->subtype != NULL) free(f->subtype);

  memset(f, 0, sizeof(XField));
}

/**
 * Destroys an X structure field, freeing up all referenced resources, and
 * destroying the field itself.
 *
 * \param f     Pointer to the field to be destroyed.
 *
 * \sa xClearField()
 */
void xDestroyField(XField *f) {
  if(!f) return;
  xClearField(f);
  free(f);
}

/**
 * Destroys the contents of an X structure, leaving the structure empty.
 *
 * @param s    Pointer to the structure to be cleared.
 *
 * @sa smaDestroyStruct()
 */
void xClearStruct(XStructure *s) {
  XField *f;

  if(s == NULL) return;

  for(f = s->firstField; f != NULL; ) {
    XField *next = f->next;
    xDestroyField(f);
    f = next;
  }

  s->firstField = NULL;
}

/**
 * Reduces the dimensions by eliminating axes that contain a singular elements. Thus a size of {1, 3, 1, 5}
 * will reduce to {3, 5} containing the same number of elements, in fewer dimensions. If any of the dimensions
 * are zero then it reduces to { 0 }.
 *
 *
 * @param[in, out] ndim     Pointer to the dimensions (will be updated in situ)
 * @param[in, out] sizes    Array of sizes along the dimensions (will be updated in situ)
 * @return                  X_SUCCESS (0) if successful or else X_SIZE_INVALID if the ndim argument is NULL, or if it is greater than zero but
 *                          the sizes argument is NULL (errno set to EINVAL in both cases)
 *
 * @see xReduceStruct()
 */
int xReduceDims(int *ndim, int *sizes) {
  static const char *fn = "xReduceDims";

  int i;

  if(ndim == NULL) return x_error(X_SIZE_INVALID, EINVAL, fn, "ndim pointer is NULL");

  if(*ndim < 1) return X_SUCCESS;

  // FIXME This condition trips up infer...
  if(sizes == NULL) return x_error(X_SIZE_INVALID, EINVAL, fn, "sizes is NULL (ndim = %d)", *ndim);

  for(i = *ndim; --i >= 0; ) if (sizes[i] == 0) {
    *ndim = 0;
    sizes[0] = 0;
    return X_SUCCESS;
  }

  for(i = *ndim; --i >= 0; ) if (sizes[i] == 1) {
    (*ndim)--;
    if(i < *ndim) memmove(&sizes[i], &sizes[i+1], (*ndim - i - 1) * sizeof(int));
    else sizes[i] = 0;
  }

  return X_SUCCESS;
}

/**
 * Eliminate the unnecessary nesting of single XField. XField arrays are used to store heterogeneous rows
 * of arrays. If just one row is used, it's by definition homogeneous, and the contents do not need to
 * be wrapped into an XField.
 *
 * @param f   Pointer to a field
 * @return    X_SUCCESS (0)
 */
static int xUnwrapField(XField *f) {
  XField *nested;

  if(f->type != X_FIELD || xGetFieldCount(f) != 1) return X_SUCCESS;

  nested = (XField *) f->value;

  if(nested->type == X_STRUCT) {
    XStructure *s = (XStructure *) nested->value;
    int i = xGetFieldCount(nested);
    while(--i >= 0) xReduceStruct(&s[i]);
  }
  else if(nested->type == X_FIELD) return xUnwrapField(nested);

  if(f->name) free(f->name);
  if(f->subtype) free(f->subtype);
  if(f->value) free(f->value);

  *f = *nested;
  return X_SUCCESS;
}

/**
 * Reduces a field by eliminating extraneous dimensions, and/or wrapping recursively.
 *
 * @param f     Pointer to a field
 * @return      X_SUCCESS (0) if successful, or else an xchange.h error code &lt;0.
 *
 * @sa xReduceStruct()
 * @sa xReduceDims()
 */
int xReduceField(XField *f) {
  if(!f) return x_error(X_NULL, EINVAL, "xReduceField", "input field is NULL");

  xReduceDims(&f->ndim, f->sizes);

  if(f->type == X_FIELD) xUnwrapField(f);
  else if(f->type == X_STRUCT) {
    XStructure *sub = (XStructure *) f->value;
    int i = xGetFieldCount(f);
    while(--i >= 0) xReduceStruct(&sub[i]);
  }

  return X_SUCCESS;
}

/**
 * Recursively eliminates unneccessary embedding of singular structures inside a structure and reduces the
 * dimensions of array fields with xReduceDims(), recursively. It will also eliminate the unnecessary wrapping
 * of a singular array into a single XField.
 *
 * @param s     Pointer to a structure.
 * @return      X_SUCCESS (0) if successful or else X_STRUCT_INVALID if the argument is NULL (errno is
 *              also set to EINVAL)
 *
 * @sa xReduceField()
 */
int xReduceStruct(XStructure *s) {
  XField *f;

  if(!s) return x_error(X_STRUCT_INVALID, EINVAL, "xReduceStruct", "input structure is NULL");

  f = s->firstField;
  if(!f) return X_SUCCESS;

  if(f->next == NULL && f->type == X_STRUCT && xGetFieldCount(f) == 1) {
    // Single structure of a single structure.
    // We can eliminate the unnecessary nesting.

    XStructure *sub = (XStructure *) f->value;
    const XField *sf;

    s->firstField = sub->firstField;

    for(sf = s->firstField; sf; sf = sf->next) if(sf->type == X_STRUCT) {
      XStructure *ss = (XStructure *) f->value;
      int i = xGetFieldCount(sf);
      while(--i >= 0) ss[i].parent = s;
    }

    xReduceStruct(s);

    free(f);
    return X_SUCCESS;
  }

  for(; f != NULL; f = f->next) xReduceField(f);

  return X_SUCCESS;
}



/**
 * Returns a pointer to the beginning of the next component in a compound ID. Leading ID separators are ignored.
 *
 * @param id    Aggregate X ID.
 * @return      Pointer to the start of the next compound ID token, or NULL if there is no more components in the ID.
 */
char *xNextIDToken(const char *id) {
  char *my_id = (char *)id;  // PJT const
  char *next;

  if(!id) return NULL;

  // Ignore leading separator.
  if(!strncmp(my_id, X_SEP, X_SEP_LENGTH)) my_id += X_SEP_LENGTH;

  next = strstr(my_id, X_SEP);
  return next ? next + X_SEP_LENGTH : NULL;
}

/**
 * Returns a copy of the next next component in a compound ID. Leading ID separators are ignored.
 *
 * @param id    Aggregate X ID.
 * @return      Pointer to the start of the next compound ID token, or NULL if there is no more components in the ID.
 */
char *xCopyIDToken(const char *id) {
  const char *next;
  char *token;
  int l;

  if(!id) {
    x_error(X_NULL, EINVAL, "xCopyIDToken", "input ID is NULL");
    return NULL;
  }

  // Ignore leading separator.
  if(!strncmp(id, X_SEP, X_SEP_LENGTH)) id += X_SEP_LENGTH;

  next = xNextIDToken(id);
  if(next) l = next - id - X_SEP_LENGTH;
  else l = strlen(id);

  token = (char *) malloc(l+1);
  if(!token) {
    x_error(0, errno, "xCopyIDToken", "malloc error");
    return NULL;
  }

  memcpy(token, id, l);
  token[l] = '\0';

  return token;
}

/**
 * Checks if the next component in a compound id matches a given token.
 *
 * @param token     Full token to check for
 * @param id        Compount X ID.
 * @return          X_SUCCESS if it's a match. Otherwise X_FAILURE or another X error if the
 *                  arguments are invalid.
 */
int xMatchNextID(const char *token, const char *id) {
  static const char *fn = "xMatchNextID";

  int L;

  if(!token) return x_error(X_NULL, EINVAL, fn, "input token is NULL");
  if(token[0] == '\0') return x_error(X_NAME_INVALID, EINVAL, fn, "input token is empty");
  if(!id) return x_error(X_NULL, EINVAL, fn, "input id is NULL");
  if(id[0] == '\0') return x_error(X_GROUP_INVALID, EINVAL, fn, "input id is empty");

  L = strlen(token);
  if(strncmp(id, token, L) != 0) return X_FAILURE;

  if(id[L] == '\0') return X_SUCCESS;

  if(strlen(id) < L + X_SEP_LENGTH) return X_FAILURE;
  if(strncmp(id + L, X_SEP, X_SEP_LENGTH)) return X_FAILURE;

  return X_SUCCESS;
}


/**
 * Returns the aggregated (hierarchical) &lt;table&gt;:&lt;key&gt; ID. The caller is responsible for calling free()
 * on the returned string after use.
 *
 * \param table     SMA-X hastable name
 * \param key       The lower-level id to concatenate.
 *
 * \return          The aggregated ID, or NULL if both arguments were NULL themselves.
 *
 * \sa xSplitID()
 */
char *xGetAggregateID(const char *table, const char *key) {
  static const char *fn = "xGetAggregateID";

  char *id;

  if(table == NULL && key == NULL) {
    x_error(0, EINVAL, fn, "both inputs are NULL");
    return NULL;
  }

  if(table == NULL) return xStringCopyOf(key);
  if(key == NULL) return xStringCopyOf(table);

  id = (char *) malloc(strlen(table) + X_SEP_LENGTH + strlen(key) + 1); // <group>:<key>
  if(!id) {
    x_error(0, errno, fn, "malloc error");
    return NULL;
  }
  sprintf(id, "%s" X_SEP "%s", table, key);

  return id;
}

/**
 * Returns the string pointer to the begining of the last separator in the ID.
 *
 * @param id    Compound SMA-X ID.
 * @return      Pointer to the beginning of the last separator in the ID, or NULL if the ID does not contain a separator.
 *
 * @sa xSplitID()
 */
char *xLastSeparator(const char *id) {
  int l;

  if(!id) {
    x_error(0, EINVAL, "xLastSeparator", "input id is NULL");
    return NULL;
  }

  l = strlen(id);

  while(--l >= 0) if(id[l] == X_SEP[0]) if(!strncmp(&id[l], X_SEP, X_SEP_LENGTH)) return (char *) &id[l];
  return NULL;
}

/**
 * Splits the id into two strings (sharing the same input buffer): (1) the id of the embedding structure, and
 * (2) the embedded field name. The original input id is string terminated after the table name. And the pointer to the key
 * part that follows after the last separator is returned in the second (optional argument).
 *
 * \param[in,out] id        String containing an aggregate ID, which will be terminated after the last substructure.
 * \param[out] pKey         Returned pointer to the second component after the separator within the same buffer. This is
 *                          not an independent pointer. Use xStringCopyOf() if you need an idependent string
 *                          on which free() can be called! The returned value pointed to may be NULL if the ID
 *                          could not be split. The argument may also be null, in which case the input string is
 *                          just terminated at the stem, without returning the second part.
 *
 * \return      X_SUCCESS (0)       if the ID was successfully split into two components.
 *              X_NULL              if the id argument is NULL.
 *              X_NAME_INVALID      if no separator was found
 *
 * \sa xGetAggregateID()
 * \sa xLastSeparator()
 */
int xSplitID(char *id, char **pKey) {
  if(id == NULL) return x_error(X_NULL, EINVAL, "xSplitID", "input id is NULL");

  // Default NULL return for the second component.
  if(pKey) *pKey = NULL;

  id = xLastSeparator(id);
  if(id) *id = '\0';
  else return X_NAME_INVALID;

  if(pKey) *pKey = id + X_SEP_LENGTH;

  return X_SUCCESS;
}

/**
 * Counts the number of fields in a structure, including the field count for all embedded
 * substructures also recursively.
 *
 * @param s           Pointer to a structure
 * @return            The total number of fields present in the structure and all its sub-structures.
 *
 * @sa xCountFields()
 */
long xDeepCountFields(const XStructure *s) {
  static const char *fn = "xDeepCountFields";

  XField *f;
  long n = 0;

  if(!s) return x_error(0, EINVAL, fn, "input structure is NULL");

  for(f = s->firstField; f != NULL; f = f->next) {
    n++;

    if(f->type == X_STRUCT) {
      XStructure *sub = (XStructure *) f->value;
      int i = xGetFieldCount(f);
      while(--i >= 0) {
        long m = xDeepCountFields(&sub[i]);
        if(m < 0) {
          x_trace(fn, f->name, m);
          return -1;
        }
        n += m;
      }
    }
  }

  return n;
}

/**
 * Sort the fields in a structure using a specific comparator function.
 *
 * @param s           The structure, whose fields to sort
 * @param cmp         The comparator function. It takes two pointers to XField locations as arguments.
 * @param recursive   Whether to apply the sorting to all ebmbedded substructures also
 * @return            X_SUCCESS (0) if successful, or else X_NULL if the structure or the comparator
 *                    function is NULL.
 *
 * @sa xSortFieldsByName()
 * @sa xReverseFieldOrder()
 */
int xSortFields(XStructure *s, int (*cmp)(const XField **f1, const XField **f2), boolean recursive) {
  static const char *fn = "xSortFields";

  XField **array, *f;
  int i, n;

  if(s == NULL || cmp == NULL) return x_error(X_NULL, EINVAL, fn, "NULL argument: s=%p, cmp=%p", s, cmp);

  for(n = 0, f = s->firstField; f != NULL; f = f->next, n++)
    if(f->type == X_STRUCT && recursive && f->value) {
      XStructure *sub = (XStructure *) f->value;
      int k = xGetFieldCount(f);
      while (--k >= 0) xSortFields(&sub[k], cmp, TRUE);
    }

  if(n < 2) return n;

  array = (XField **) malloc(n * sizeof(XField *));
  if(!array) return x_error(X_FAILURE, errno, fn, "alloc error (%d XField)", n);

  for(n = 0, f = s->firstField; f != NULL;) {
    XField *next = f->next;
    f->next = NULL;
    array[n++] = f;
    f = next;
  }
  s->firstField = NULL;

  qsort(array, n, sizeof(XField *), (int (*)(const void *, const void *)) cmp);

  s->firstField = array[0];
  for(i = 1, f = s->firstField; i < n; i++, f = f->next) f->next = array[i];

  free(array);

  return X_SUCCESS;
}


static int XFieldNameCmp(const XField **f1, const XField **f2) {
  return strcmp((*f1)->name, (*f2)->name);
}

/**
 * Sorts the fields of a structure by field name, in ascending alphabetical order.
 *
 * @param s           The structure, whose fields to sort
 * @param recursive   Whether to apply the sorting to all ebmbedded substructures also
 * @return            X_SUCCESS (0) if successful, or else X_NULL if the structure is NULL.
 *
 * @sa xReverseFieldOrder()
 */
int xSortFieldsByName(XStructure *s, boolean recursive) {
  prop_error("xSortFieldsByName", xSortFields(s, XFieldNameCmp, recursive));
  return X_SUCCESS;
}

/**
 * Reverse the order of fields in a structure.
 *
 * @param s           The structure, whose field order to reverse.
 * @param recursive   Whether to apply the reversal to all ebmbedded substructures also
 * @return            X_SUCCESS (0) if successful, or else X_NULL if the structure is NULL.
 *
 * @sa xSortFields()
 * @sa xSortFieldsByName()
 * @sa xInsertField()
 */
int xReverseFieldOrder(XStructure *s, boolean recursive) {
  XField *f, *rev = NULL;

  if(s == NULL) return x_error(X_NULL, EINVAL, "xReverseFieldOrder", "input structure is NULL");

  f = s->firstField;
  s->firstField = NULL;

  while(f != NULL) {
    XField *next = f->next;
    f->next = rev;
    rev = f;

    if(f->type == X_STRUCT && recursive && f->value) {
      XStructure *sub = (XStructure *) f->value;
      int i = xGetFieldCount(f);
      while(--i >= 0) xReverseFieldOrder(&sub[i], TRUE);
    }

    f = next;
  }

  s->firstField = rev;
  return X_SUCCESS;
}
