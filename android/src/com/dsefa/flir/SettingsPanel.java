package com.dsefa.flir;
import android.app.*;
import android.view.*;
import android.widget.*;
import java.util.Locale;
import java.util.function.DoubleConsumer;

/** Compact mode-specific controls; edit values directly or use fine +/- steps. */
final class SettingsPanel {
    private final Activity a;private final Thermal.Settings s;private final Runnable changed;
    private final LinearLayout root;private final Dialog dialog;
    private LinearLayout manual,adaptive,contrast,denoise,detail,background;
    SettingsPanel(Activity a,Thermal.Settings s,Runnable changed){this.a=a;this.s=s;this.changed=changed;
        root=new LinearLayout(a);root.setOrientation(1);root.setPadding(dp(18),dp(12),dp(18),dp(24));
        dialog=new Dialog(a);ScrollView scroll=new ScrollView(a);scroll.addView(root);dialog.setContentView(scroll);build();}
    private int dp(int v){return (int)(v*a.getResources().getDisplayMetrics().density+.5f);}
    private void title(String text){TextView v=new TextView(a);v.setText(text);v.setTextSize(13);v.setTextColor(0xff7fded2);v.setPadding(0,dp(20),0,dp(10));root.addView(v);}
    private LinearLayout group(){LinearLayout g=new LinearLayout(a);g.setOrientation(1);root.addView(g);return g;}
    private void select(LinearLayout parent,String label,String[] options,String value,java.util.function.Consumer<String> set){
        TextView text=new TextView(a);text.setText(label);parent.addView(text);Spinner v=new Spinner(a);v.setAdapter(new ArrayAdapter<>(a,android.R.layout.simple_spinner_dropdown_item,options));
        for(int i=0;i<options.length;i++)if(options[i].equals(value))v.setSelection(i);parent.addView(v);
        v.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){public void onNothingSelected(android.widget.AdapterView<?> p){}public void onItemSelected(android.widget.AdapterView<?> p,View child,int n,long id){set.accept(options[n]);changed.run();visibility();}});}
    private void numeric(LinearLayout parent,String label,double value,double min,double max,double step,DoubleConsumer set){
        TextView text=new TextView(a);text.setText(label);text.setTextSize(12);text.setPadding(0,dp(9),0,0);parent.addView(text);
        LinearLayout row=new LinearLayout(a);parent.addView(row);EditText edit=new EditText(a);edit.setSingleLine();edit.setTextSize(14);edit.setInputType(8194|4096);edit.setText(String.format(Locale.US,"%s",value));
        Runnable apply=()->{try{double n=Double.parseDouble(edit.getText().toString());if(!Double.isFinite(n)||n<min||n>max)throw new IllegalArgumentException();set.accept(n);changed.run();}catch(Exception e){edit.setError("Range: "+min+" … "+max);}};
        Button minus=new Button(a);minus.setText("−");row.addView(minus,new LinearLayout.LayoutParams(dp(58),dp(48)));row.addView(edit,new LinearLayout.LayoutParams(0,dp(48),1));Button plus=new Button(a);plus.setText("+");row.addView(plus,new LinearLayout.LayoutParams(dp(58),dp(48)));
        java.util.function.DoubleConsumer stepBy=delta->{try{double n=Math.max(min,Math.min(max,Double.parseDouble(edit.getText().toString())+delta));edit.setText(String.format(Locale.US,"%.3f",n).replaceAll("0+$","").replaceAll("\\.$",""));apply.run();}catch(Exception ignored){edit.setError("Enter a number");}};
        minus.setOnClickListener(v->stepBy.accept(-step));plus.setOnClickListener(v->stepBy.accept(step));
        edit.setOnFocusChangeListener((v,focus)->{if(!focus)apply.run();});edit.setOnEditorActionListener((v,action,event)->{apply.run();return false;});
    }
    private void toggle(String label,boolean value,java.util.function.Consumer<Boolean> set){Switch v=new Switch(a);v.setText(label);v.setTextSize(13);v.setPadding(0,dp(12),0,dp(12));v.setChecked(value);root.addView(v);v.setOnCheckedChangeListener((b,on)->{set.accept(on);changed.run();});}
    private void action(String label,Runnable r){Button b=new Button(a);b.setText(label);b.setAllCaps(false);root.addView(b);b.setOnClickListener(v->r.run());}
    private void build(){title("DISPLAY");select(root,"Palette",Thermal.PALETTES,s.palette,v->s.palette=v);select(root,"Scale",Thermal.MODES,s.scale,v->s.scale=v);
        numeric(root,"Tone",s.tone,-100,100,1,v->s.tone=v);numeric(root,"Display span % · lower = more sensitivity",s.span,25,400,5,v->s.span=v);
        manual=group();numeric(manual,"Manual minimum °C",s.low,-100,1000,.1,v->{if(v>=s.high)throw new IllegalArgumentException();s.low=v;});numeric(manual,"Manual maximum °C",s.high,-99,1500,.1,v->{if(v<=s.low)throw new IllegalArgumentException();s.high=v;});
        contrast=group();numeric(contrast,"Contrast limit",s.contrast,1,4,.1,v->s.contrast=v);adaptive=group();numeric(adaptive,"Minimum display span °C",s.minSpan,.1,100, .1,v->s.minSpan=v);denoise=group();numeric(denoise,"Denoise % · display only",s.denoise,0,100,5,v->s.denoise=v);
        detail=group();numeric(detail,"Local detail %",s.detail,0,100,5,v->s.detail=v);
        background=group();numeric(background,"Deadband °C",s.deadband,0,2,.05,v->s.deadband=v);numeric(background,"Minimum hot span °C",s.hotSpan,.5,20,.1,v->s.hotSpan=v);numeric(background,"Learning time · seconds",s.learningSeconds,1,3600,10,v->s.learningSeconds=v);
        toggle("Smooth interpolation / range adaptation",s.smooth,v->s.smooth=v);
        action("Reset display",()->{Thermal.Settings d=new Thermal.Settings();s.palette=d.palette;s.scale=d.scale;s.low=d.low;s.high=d.high;s.tone=0;s.span=100;s.contrast=d.contrast;s.minSpan=d.minSpan;s.detail=d.detail;s.denoise=d.denoise;s.deadband=d.deadband;s.hotSpan=d.hotSpan;s.learningSeconds=d.learningSeconds;s.smooth=true;changed.run();dialog.dismiss();new SettingsPanel(a,s,changed).show();});
        title("TEMPERATURE / RADIOMETRY");numeric(root,"Emissivity ε",s.emissivity,.1,1,.01,v->s.emissivity=v);numeric(root,"Reflected temperature °C",s.reflected,-100,1000,.5,v->s.reflected=v);numeric(root,"Calibration offset °C",s.offset,-100,100, .1,v->s.offset=v);
        toggle("3 × 3 point average",s.average,v->s.average=v);toggle("Fahrenheit (off = Celsius)",s.fahrenheit,v->s.fahrenheit=v);
        action("Reset temperature",()->{s.emissivity=.95;s.reflected=20;s.offset=0;s.average=true;s.fahrenheit=false;changed.run();dialog.dismiss();new SettingsPanel(a,s,changed).show();});
        TextView note=new TextView(a);note.setText("Display processing never changes measured temperatures. Temperature values are estimates using the existing calibration model, not laboratory or medical measurements.\n\nSaved images preserve their colours; older RAW files remain reprocessable. Visible / MSX is not available.");note.setTextSize(11);note.setTextColor(0xff8ba1b5);note.setPadding(0,dp(16),0,dp(12));root.addView(note);
        action("Done",()->{root.clearFocus();dialog.dismiss();});visibility();}
    private void visibility(){if(manual==null||background==null)return;manual.setVisibility(s.scale.equals("Manual")?View.VISIBLE:View.GONE);contrast.setVisibility(s.scale.equals("Auto")||s.scale.equals("Detail")?View.VISIBLE:View.GONE);adaptive.setVisibility(!s.scale.equals("Manual")&&!s.scale.equals("Background relative")?View.VISIBLE:View.GONE);denoise.setVisibility(s.scale.equals("Manual")?View.GONE:View.VISIBLE);detail.setVisibility(s.scale.equals("Detail")?View.VISIBLE:View.GONE);background.setVisibility(s.scale.equals("Background relative")?View.VISIBLE:View.GONE);}
    void show(){dialog.show();Window w=dialog.getWindow();if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(0xff111923));w.setGravity(Gravity.BOTTOM);w.setLayout(-1,(int)(a.getResources().getDisplayMetrics().heightPixels*.86));}}
}
